#!/usr/bin/env python3
"""
Cluster sequences by group
"""
# Info
__author__ = 'Christopher Bolen, Jason Anthony Vander Heiden, Ruoyi Jiang'
from presto import __version__, __date__

# Imports
import os
import shutil
import sys
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent
from time import time
from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
import csv
import tempfile

from subprocess import check_output, CalledProcessError, STDOUT

from Bio import SeqIO
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

from presto.IO import printError

# Presto imports
from presto.Defaults import default_delimiter, default_barcode_field, \
                            default_cluster_field, default_out_args, \
                            default_usearch_exec, default_vsearch_exec, default_cdhit_exec
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.Annotation import parseAnnotation, flattenAnnotation, mergeAnnotation
from presto.Applications import runCDHit, runUClust, default_max_memory
from presto.IO import countSeqFile, getFileType, getOutputHandle, openFile, printLog, printMessage, \
                      printProgress, readSeqFile, printError, printWarning
from presto.Sequence import indexSeqSets
from presto.Multiprocessing import SeqResult, manageProcesses, feedSeqQueue, \
                                   collectSeqQueue

# Defaults
choices_cluster_tool = ['usearch', 'vsearch', 'cd-hit-est']
default_cluster_tool = 'usearch'
default_cluster_exec = default_usearch_exec
default_cluster_ident = 0.9
default_length_ratio = 0.0
default_cluster_prefix=''

min_cluster_ident = {'cd-hit-est': 0.80,
                     'usearch': 0.0,
                     'vsearch': 0.0}

def runVSearch(seq_list,
               ident=0.0,
               length_ratio=0.0,
               seq_start=0,
               seq_end=None,
               max_memory=None,
               threads=None,
               cluster_exec='vsearch',
               min_word_match=12):
    """
    Cluster sequences using VSEARCH --cluster_fast.

    This is intentionally separate from pRESTO's runUClust because
    VSEARCH uses GNU-style long options (--option), while the pRESTO
    runUClust wrapper builds USEARCH-style options (-option).

    Returns:
        dict mapping cluster number (1-based) to sequence IDs.
    """

    gap_trans = str.maketrans({'-': 'N', '.': 'N'})

    def _clean(rec, i, j):
        seq = str(rec.seq[i:j])
        seq = seq.translate(gap_trans)
        return SeqRecord(
            Seq(seq),
            id=rec.id,
            name=rec.name,
            description=rec.description
        )

    # Make a trimmed/masked copy without modifying original records.
    seq_trimmed = [
        _clean(x, seq_start, seq_end)
        for x in seq_list
    ]

    # Return sequence if only one sequence is present.
    if len(seq_trimmed) < 2:
        return {1: [seq_trimmed[0].id]}

    # Reject empty sequences after trimming.
    if any(len(x.seq) == 0 for x in seq_trimmed):
        return None

    # Temporary input/output files.
    in_handle = tempfile.NamedTemporaryFile(
        mode='w+t',
        encoding='utf-8'
    )
    out_handle = tempfile.NamedTemporaryFile(
        mode='w+t',
        encoding='utf-8'
    )

    # VSEARCH uses --long-option syntax.
    cmd = [
        cluster_exec,
        '--cluster_fast', in_handle.name,
        '--uc', out_handle.name,
        '--id', str(ident),
        '--minsl', str(length_ratio),
        '--qmask', 'none',
        '--minseqlength', '1',
        '--minwordmatches', str(min_word_match),
    ]

    # Do NOT pass "--threads none".
    if threads is not None:
        cmd.extend([
            '--threads', str(threads)
        ])

    # Write FASTA input.
    SeqIO.write(
        seq_trimmed,
        in_handle,
        'fasta-2line'
    )
    in_handle.flush()
    in_handle.seek(0)

    # Run VSEARCH.
    try:
        check_output(
            cmd,
            stderr=STDOUT,
            shell=False,
            universal_newlines=True
        )
    except CalledProcessError as e:
        printError(
            'Running command: %s\n%s'
            % (' '.join(cmd), e.output)
        )

    # Parse VSEARCH UC output.
    cluster_dict = {}

    for row in csv.reader(out_handle, delimiter='\t'):
        if not row:
            continue

        # UC:
        # 0 = record type
        # 1 = cluster number
        # 8 = sequence ID
        #
        # S = centroid
        # H = hit
        if row[0] in ('H', 'S'):
            key = int(row[1]) + 1
            hit = row[8].split()[0]

            if key not in cluster_dict:
                cluster_dict[key] = []

            cluster_dict[key].append(hit)

    in_handle.close()
    out_handle.close()

    return cluster_dict
def runUSEARCH(
    seq_list,
    ident=0.0,
    length_ratio=0.0,
    seq_start=0,
    seq_end=None,
    max_memory=None,
    threads=None,
    cluster_exec='usearch',
    min_word_match=None,
):
    """
    Cluster sequences using USEARCH -cluster_fast.

    This wrapper intentionally does not pass -minwordmatches because
    the USEARCH binaries supported by this pipeline do not accept it.
    `min_word_match` is accepted (and ignored) so this function has the same
    signature as runVSearch/runCDHit -- clusterBarcodes calls whichever tool
    was selected with the same kwargs, and usearch is the default tool, so
    without this every ClusterSets.barcode run failed with
    "unexpected keyword argument 'min_word_match'" unless a user happened to
    switch to vsearch first.
    """

    gap_trans = str.maketrans({
        '-': 'N',
        '.': 'N'
    })

    def _clean(rec, i, j):
        seq = str(rec.seq[i:j])
        seq = seq.translate(gap_trans)

        return SeqRecord(
            Seq(seq),
            id=rec.id,
            name=rec.name,
            description=rec.description
        )

    seq_trimmed = [
        _clean(x, seq_start, seq_end)
        for x in seq_list
    ]

    # Same behavior as pRESTO runUClust
    if len(seq_trimmed) < 2:
        if seq_trimmed:
            return {1: [seq_trimmed[0].id]}
        return {}

    if any(len(x.seq) == 0 for x in seq_trimmed):
        return None

    in_handle = tempfile.NamedTemporaryFile(
        mode='w+t',
        encoding='utf-8'
    )

    out_handle = tempfile.NamedTemporaryFile(
        mode='w+t',
        encoding='utf-8'
    )

    cmd = [
        cluster_exec,
        '-cluster_fast',
        in_handle.name,

        '-uc',
        out_handle.name,

        '-id',
        str(ident),

        '-minsl',
        str(length_ratio),

        '-qmask',
        'none',

        '-minseqlength',
        '1',
    ]

    # Don't pass "-threads None"
    if threads is not None:
        cmd.extend([
            '-threads',
            str(threads)
        ])

    SeqIO.write(
        seq_trimmed,
        in_handle,
        'fasta-2line'
    )

    in_handle.flush()
    in_handle.seek(0)

    try:
        check_output(
            cmd,
            stderr=STDOUT,
            shell=False,
            universal_newlines=True
        )

    except CalledProcessError as e:
        printError(
            'Running command: %s\n%s'
            % (' '.join(cmd), e.output)
        )

        in_handle.close()
        out_handle.close()
        return None

    # Parse USEARCH UC output
    cluster_dict = {}

    out_handle.seek(0)

    for row in csv.reader(
        out_handle,
        delimiter='\t'
    ):
        if not row:
            continue

        if row[0] in ('H', 'S'):
            key = int(row[1]) + 1
            hit = row[8].split()[0]

            if key not in cluster_dict:
                cluster_dict[key] = []

            cluster_dict[key].append(hit)

    in_handle.close()
    out_handle.close()

    return cluster_dict

map_cluster_tool = {'cd-hit-est': runCDHit,
                    'usearch': runUSEARCH,
                    'vsearch': runVSearch}
def processQueue(alive, data_queue, result_queue,
                 cluster_func, cluster_args={},
                 cluster_field=default_cluster_field,
                 cluster_prefix=default_cluster_prefix,
                 delimiter=default_delimiter):
    """
    Pulls from data queue, performs calculations, and feeds results queue

    Arguments:
      alive : a multiprocessing.Value boolean controlling whether processing
              continues; when False function returns.
      data_queue : a multiprocessing.Queue holding data to process.
      result_queue : a multiprocessing.Queue to hold processed results.
      cluster_func : the function to use for clustering.
      cluster_args : a dictionary of optional arguments for the clustering function.
      cluster_field : string defining the output cluster field name.
      cluster_prefix : string defining a prefix for the cluster identifier.
      delimiter : a tuple of delimiters for (annotations, field/values, value lists).

    Returns:
      None
    """
    try:
        # Iterator over data queue until sentinel object reached
        while alive.value:
            # Get data from queue
            if data_queue.empty():  continue
            else:  data = data_queue.get()
            # Exit upon reaching sentinel
            if data is None:  break

            # Define result object
            result = SeqResult(data.id, data.data)
            result.log['BARCODE'] = data.id
            result.log['SEQCOUNT'] = len(data)

            # Perform clustering
            cluster_dict = cluster_func(data.data, **cluster_args)

            # Process failed result
            if cluster_dict is None:
                # Update log
                result.log['CLUSTERS'] = 0
                for i, seq in enumerate(data.data, start=1):
                    result.log['CLUST0-%i' % i] = str(seq.seq)

                # Feed results queue and continue
                result_queue.put(result)
                continue

            # Get number of clusters
            result.log['CLUSTERS'] = len(cluster_dict)

            # Update sequence annotations with cluster assignments
            results = list()
            seq_dict = {s.id: s for s in data.data}
            for cluster, id_list in cluster_dict.items():
                for i, seq_id in enumerate(id_list, start=1):
                    # Add cluster annotation
                    seq = seq_dict[seq_id]
                    label = '%s%i' % (cluster_prefix, cluster)
                    header = parseAnnotation(seq.description, delimiter=delimiter)
                    header = mergeAnnotation(header, {cluster_field: label}, delimiter=delimiter)
                    seq.id = seq.name = flattenAnnotation(header, delimiter=delimiter)
                    seq.description = ''

                    # Update log and results
                    result.log['CLUST%i-%i' % (cluster, i)] = str(seq.seq)
                    results.append(seq)

            # Check results
            result.results = results
            result.valid = (len(results) == len(seq_dict))
            # Feed results to result queue
            result_queue.put(result)
        else:
            sys.stderr.write('PID %s> Error in sibling process detected. Cleaning up.\n' \
                             % os.getpid())

            return None
    except:
        alive.value = False
        printError('Error processing sequence set with ID: %s.' % data.id, exit=False)
        raise

    return None


def clusterSets(seq_file, ident=default_cluster_ident, length_ratio=default_length_ratio,
                seq_start=0, seq_end=None, set_field=default_barcode_field, cluster_field=default_cluster_field,
                cluster_prefix=default_cluster_prefix, cluster_memory=default_max_memory,
                cluster_tool=default_cluster_tool, cluster_exec=default_cluster_exec,
                out_file=None, out_args=default_out_args, nproc=None, queue_size=None):
    """
    Performs clustering on sets of sequences

    Arguments:
      seq_file : the sample sequence file name.
      ident : the identity threshold for clustering sequences.
      length_ratio : minimum short/long length ratio allowed within a cluster.
      seq_start : the start position to trim sequences at before clustering.
      seq_end : the end position to trim sequences at before clustering.
      set_field : the annotation containing set IDs.
      cluster_field : the name of the output cluster field.
      cluster_prefix : string defining a prefix for the cluster identifier.
      cluster_memory : cd-hit-est max memory limit (Mb)
      cluster_exec : the path to the clustering executable.
      cluster_tool : the clustering tool to use; one of cd-hit or usearch.
            out_file : output file name. Automatically generated from the input file if None.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.
      nproc : the number of processQueue processes;
              if None defaults to the number of CPUs.
      queue_size : maximum size of the argument queue;
                   if None defaults to 2*nproc.

    Returns:
      str: the clustered output file name.
    """
    # Print parameter info
    log = OrderedDict()
    log['START'] = 'ClusterSets'
    log['COMMAND'] = 'set'
    log['FILE'] = os.path.basename(seq_file)
    log['IDENTITY'] = ident
    log['SEQUENCE_START'] = seq_start
    log['SEQUENCE_END'] = seq_end
    log['SET_FIELD'] = set_field
    log['CLUSTER_FIELD'] = cluster_field
    log['CLUSTER_PREFIX'] = cluster_prefix
    log['CLUSTER_TOOL'] = cluster_tool
    log['NPROC'] = nproc
    printLog(log)

    # Set cluster tool
    try:
        cluster_func = map_cluster_tool.get(cluster_tool)
    except:
        printError('Invalid clustering tool %s.' % cluster_tool)

    # Check the minimum identity
    if ident < min_cluster_ident[cluster_tool]:
        printError('Minimum identity %s too low for clustering tool %s.' % (str(ident), cluster_tool))

    # Define cluster function parameters
    cluster_args = {'cluster_exec': cluster_exec,
                    'ident': ident,
                    'length_ratio': length_ratio,
                    'seq_start': seq_start,
                    'seq_end': seq_end,
                    'max_memory': cluster_memory}

    # Define feeder function and arguments
    index_args = {'field': set_field, 'delimiter': out_args['delimiter']}
    feed_func = feedSeqQueue
    feed_args = {'seq_file': seq_file,
                 'index_func': indexSeqSets,
                 'index_args': index_args}
    # Define worker function and arguments
    work_func = processQueue
    work_args = {'cluster_func': cluster_func,
                 'cluster_args': cluster_args,
                 'cluster_field': cluster_field,
                 'cluster_prefix': cluster_prefix,
                 'delimiter': out_args['delimiter']}
    # Define collector function and arguments
    collect_func = collectSeqQueue
    collect_args = {'seq_file': seq_file,
                    'label': 'cluster',
                    'out_file': out_file,
                    'out_args': out_args,
                    'index_field': set_field}

    # Call process manager
    result = manageProcesses(feed_func, work_func, collect_func,
                             feed_args, work_args, collect_args,
                             nproc, queue_size)

    # Print log
    log = OrderedDict()
    log['OUTPUT'] = result['log'].pop('OUTPUT')
    for k, v in result['log'].items():  log[k] = v
    log['END'] = 'ClusterSets'
    printLog(log)

    return result['out_files']


def clusterAll(seq_file, ident=default_cluster_ident, length_ratio=default_length_ratio,
               seq_start=0, seq_end=None, cluster_field=default_cluster_field,
               cluster_prefix=default_cluster_prefix, cluster_memory=default_max_memory,
               cluster_tool=default_cluster_tool, cluster_exec=default_cluster_exec,
               out_file=None, out_args=default_out_args, nproc=None):
    """
    Performs clustering on all sequences

    Arguments:
      seq_file : the sample sequence file name.
      ident : the identity threshold for clustering sequences.
      length_ratio : minimum short/long length ratio allowed within a cluster.
      seq_start : the start position to trim sequences at before clustering.
      seq_end : the end position to trim sequences at before clustering.
      cluster_field : the name of the output cluster field.
      cluster_prefix : string defining a prefix for the cluster identifier.
      cluster_memory : cd-hit-est max memory limit (Mb)
      cluster_tool : the clustering tool to use; one of cd-hit or usearch.
      cluster_exec : the path to the executable for usearch.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : output arguments.
      nproc : the number of processQueue processes;
              if None defaults to the number of CPUs

    Returns:
      str : the clustered output file name
    """
    # Function to modify SeqRecord header with cluster identifier
    def _header(seq, cluster, field=cluster_field, prefix=cluster_prefix,
                delimiter=out_args['delimiter']):
        label = '%s%i' % (prefix, cluster)
        header = parseAnnotation(seq.description, delimiter=delimiter)
        header = mergeAnnotation(header, {field: label}, delimiter=delimiter)
        seq.id = seq.name = flattenAnnotation(header, delimiter=delimiter)
        seq.description = ''
        return seq

    # Print parameter info
    log = OrderedDict()
    log['START'] = 'ClusterSets'
    log['COMMAND'] = 'all'
    log['FILE'] = os.path.basename(seq_file)
    log['IDENTITY'] = ident
    log['SEQUENCE_START'] = seq_start
    log['SEQUENCE_END'] = seq_end
    log['CLUSTER_FIELD'] = cluster_field
    log['CLUSTER_PREFIX'] = cluster_prefix
    log['CLUSTER_TOOL'] = cluster_tool
    log['NPROC'] = nproc
    printLog(log)

    # Set cluster tool
    try:
        cluster_func = map_cluster_tool.get(cluster_tool)
    except:
        printError('Invalid clustering tool %s.' % cluster_tool)

    # Check the minimum identity
    if ident < min_cluster_ident[cluster_tool]:
        printError('Minimum identity %s too low for clustering tool %s.' % (str(ident), cluster_tool))

    # Count sequence file and parse into a list of SeqRecords
    result_count = countSeqFile(seq_file)
    seq_iter = readSeqFile(seq_file)

    # Perform clustering
    start_time = time()
    printMessage('Running %s' % cluster_tool, start_time=start_time, width=25)
    cluster_dict = cluster_func(seq_iter, ident=ident, length_ratio=length_ratio,
                                seq_start=seq_start, seq_end=seq_end,
                                max_memory=cluster_memory,
                                threads=nproc, cluster_exec=cluster_exec)
    printMessage('Done', start_time=start_time, end=True, width=25)

    # Determine file type
    if out_args['out_type'] is None:
        out_args['out_type'] = getFileType(seq_file)

    # Open output file handles
    if out_file is not None:
        # For explicit output files, check if gzip is needed
        if out_args.get('gzip_output', False) and not out_file.endswith('.gz'):
            out_file = out_file + '.gz'
        pass_handle = openFile(out_file, 'w')
    else:
        pass_handle = getOutputHandle(seq_file,
                                      'cluster-pass',
                                      out_dir=out_args['out_dir'],
                                      out_name=out_args['out_name'],
                                      out_type=out_args['out_type'],
                                      gzip_output=out_args.get('gzip_output', False))

    # Open indexed sequence file
    seq_dict = readSeqFile(seq_file, index=True)

    # Iterate over sequence records and update header with cluster annotation
    start_time = time()
    rec_count = pass_count = 0
    for cluster, id_list in cluster_dict.items():
        printProgress(rec_count, result_count, 0.05, start_time=start_time)
        rec_count += len(id_list)

        # Define output sequences
        seq_output = [_header(seq_dict[x], cluster) for x in id_list]

        # Write output
        pass_count += len(seq_output)
        SeqIO.write(seq_output, pass_handle, out_args['out_type'])

    # Update progress
    printProgress(rec_count, result_count, 0.05, start_time=start_time)

    # Print log
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['CLUSTERS'] = len(cluster_dict)
    log['SEQUENCES'] = result_count
    log['PASS'] = pass_count
    log['FAIL'] = rec_count - pass_count
    log['END'] = 'ClusterSets'
    printLog(log)

    # Close handles
    pass_handle.close()

    return pass_handle.name


def clusterBarcodes(seq_file, ident=default_cluster_ident, length_ratio=default_length_ratio,
                    barcode_field=default_barcode_field, cluster_field=default_cluster_field,
                    cluster_prefix=default_cluster_prefix, cluster_memory=default_max_memory,
                    cluster_tool=default_cluster_tool, cluster_exec=default_cluster_exec,
                    out_file=None, out_args=default_out_args, nproc=None):
    """
    Performs clustering on sets of sequences

    Arguments:
      seq_file : the sample sequence file name.
      ident : the identity threshold for clustering sequences.
      length_ratio : minimum short/long length ratio allowed within a cluster.
      barcode_field : the annotation field containing barcode sequences.
      cluster_field : the name of the output cluster field.
      cluster_prefix : string defining a prefix for the cluster identifier.
      cluster_memory : cd-hit-est max memory limit (Mb)
      seq_start : the start position to trim sequences at before clustering.
      seq_end : the end position to trim sequences at before clustering.
      cluster_tool : the clustering tool to use; one of cd-hit or usearch.
      cluster_exec : the path to the executable for usearch.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : output arguments.
      nproc : the number of processQueue processes;
              if None defaults to the number of CPUs.

    Returns:
      str: the clustered output file name
    """
    # Function to modify SeqRecord header with cluster identifier
    def _header(seq, cluster, field=cluster_field, prefix=cluster_prefix,
                delimiter=out_args['delimiter']):
        label = '%s%i' % (prefix, cluster)
        header = parseAnnotation(seq.description, delimiter=delimiter)
        header = mergeAnnotation(header, {field: label}, delimiter=delimiter)
        seq.id = seq.name = flattenAnnotation(header, delimiter=delimiter)
        seq.description = ''
        return seq

    # Function to extract to make SeqRecord object from a barcode annotation
    def _barcode(seq, field=barcode_field, delimiter=out_args['delimiter']):
        header = parseAnnotation(seq.description, delimiter=delimiter)
        return SeqRecord(Seq(header[field]), id=seq.id)

    # Print parameter info
    log = OrderedDict()
    log['START'] = 'ClusterSets'
    log['COMMAND'] = 'barcode'
    log['FILE'] = os.path.basename(seq_file)
    log['IDENTITY'] = ident
    log['BARCODE_FIELD'] = barcode_field
    log['CLUSTER_FIELD'] = cluster_field
    log['CLUSTER_PREFIX'] = cluster_prefix
    log['CLUSTER_TOOL'] = cluster_tool
    log['NPROC'] = nproc
    printLog(log)

    # Set cluster tool
    try:
        cluster_func = map_cluster_tool.get(cluster_tool)
    except:
        printError('Invalid clustering tool %s.' % cluster_tool)

    # Check the minimum identity
    if ident < min_cluster_ident[cluster_tool]:
        printError('Minimum identity %s too low for clustering tool %s.' % (str(ident), cluster_tool))

    # Count sequence file and parse into a list of SeqRecords
    result_count = countSeqFile(seq_file)
    barcode_iter = (_barcode(x) for x in readSeqFile(seq_file))

    # Perform clustering, note reduced min_word_match compared to cluster sets
    # see https://github.com/torognes/vsearch/issues/328
    start_time = time()
    printMessage('Running %s' % cluster_tool, start_time=start_time, width=25)
    cluster_dict = cluster_func(barcode_iter, ident=ident, length_ratio=length_ratio,
                                seq_start=0, seq_end=None, max_memory=cluster_memory,
                                threads=nproc, cluster_exec=cluster_exec,
                                min_word_match=1)
    printMessage('Done', start_time=start_time, end=True, width=25)

    # Determine file type
    if out_args['out_type'] is None:
        out_args['out_type'] = getFileType(seq_file)

    # Open output file handles
    if out_file is not None:
        # For explicit output files, check if gzip is needed
        if out_args.get('gzip_output', False) and not out_file.endswith('.gz'):
            out_file = out_file + '.gz'
        pass_handle = openFile(out_file, 'w')
    else:
        pass_handle = getOutputHandle(seq_file,
                                      'cluster-pass',
                                      out_dir=out_args['out_dir'],
                                      out_name=out_args['out_name'],
                                      out_type=out_args['out_type'],
                                      gzip_output=out_args.get('gzip_output', False))

    # Open indexed sequence file
    seq_dict = readSeqFile(seq_file, index=True)

    # Iterate over sequence records and update header with cluster annotation
    start_time = time()
    rec_count = pass_count = 0
    for cluster, id_list in cluster_dict.items():
        printProgress(rec_count, result_count, 0.05, start_time=start_time)
        rec_count += len(id_list)

        # TODO:  make a generator. Figure out how to get pass_count updated
        # Define output sequences
        seq_output = [_header(seq_dict[x], cluster) for x in id_list]

        # Write output
        pass_count += len(seq_output)
        SeqIO.write(seq_output, pass_handle, out_args['out_type'])

    # Update progress
    printProgress(rec_count, result_count, 0.05, start_time=start_time)

    # Print log
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name)
    log['CLUSTERS'] = len(cluster_dict)
    log['SEQUENCES'] = result_count
    log['PASS'] = pass_count
    log['FAIL'] = rec_count - pass_count
    log['END'] = 'ClusterSets'
    printLog(log)

    # Close handles
    pass_handle.close()

    return pass_handle.name


def getArgParser():
    """
    Defines the ArgumentParser

    Returns:
      argparse.ArgumentParser: argument parser object.
    """
    # Define output file names and header fields
    fields = dedent(
             '''
             output files:
                 cluster-pass
                    clustered reads.
                 cluster-fail
                    raw reads failing clustering.

             output annotation fields:
                 CLUSTER
                    a numeric cluster identifier defining the within-group cluster.
             ''')

    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s %s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', dest='command', metavar='',
                                       help='Clustering method')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Parent parser of common arguments
    parent_parser = ArgumentParser(formatter_class=CommonHelpFormatter, add_help=False)
    group_parent = parent_parser.add_argument_group('common clustering arguments')
    group_parent.add_argument('-k', action='store', dest='cluster_field', type=str,
                              default=default_cluster_field,
                              help='''The name of the output annotation field to add with the
                                   cluster information for each sequence.''')
    group_parent.add_argument('--ident', action='store', dest='ident', type=float,
                              default=default_cluster_ident,
                              help='''The sequence identity threshold to use for clustering. 
                                   Note, how identity is calculated is specific to the clustering 
                                   application used.''')
    group_parent.add_argument('--length', action='store', dest='length_ratio', type=float,
                              default=default_length_ratio,
                              help='''The minimum allowed shorter/longer sequence length ratio allowed 
                                   within a cluster. Setting this value to 1.0 will require identical 
                                   length matches within clusters. A value of 0.0 will allow clusters
                                   containing any length of substring.''')
    group_parent.add_argument('--prefix', action='store', dest='cluster_prefix', type=str,
                              default=default_cluster_prefix,
                               help='''A string to use as the prefix for each cluster identifier.
                                    By default, cluster identifiers will be numeric values only.''')
    group_parent.add_argument('--cluster', action='store', dest='cluster_tool',
                              choices=choices_cluster_tool, default=default_cluster_tool,
                              help='''The clustering tool to use for assigning clusters. 
                                   Must be one of usearch, vsearch or cd-hit-est. Note, for 
                                   cd-hit-est the default maximum memory limit is set to 3GB.''')
    group_parent.add_argument('--mem', action='store', dest='cluster_memory',
                              default=default_max_memory,
                              help='''The maximum memory limit for cd-hit-est in MB. 
                                   Ignored if using usearch or vsearch.''')
    group_parent.add_argument('--exec', action='store', dest='cluster_exec', default=None,
                              help='The name or path of the usearch, vsearch or cd-hit-est executable.')

    # Sequence set clustering arguments
    parser_set = subparsers.add_parser('set',
                                       parents=[getCommonArgParser(log=True, multiproc=True), parent_parser],
                                       formatter_class=CommonHelpFormatter, add_help=False,
                                       help='Cluster sequences within annotation sets.',
                                       description='Cluster sequences within annotation sets.')
    group_set = parser_set.add_argument_group('grouped sequence clustering arguments')
    group_set.add_argument('-f', action='store', dest='set_field', type=str,
                           default=default_barcode_field,
                           help='''The annotation field containing annotations, such as UMI
                                barcode, for sequence grouping.''')
    group_set.add_argument('--start', action='store', dest='seq_start', type=int, default=0,
                           help='''The start of the region to be used for clustering.
                                Together with --end, this parameter can be used to specify a
                                subsequence of each read to use in the clustering algorithm.''')
    group_set.add_argument('--end', action='store', dest='seq_end', type=int,
                           help='The end of the region to be used for clustering.')
    parser_set.set_defaults(func=clusterSets)

    # Total sequence clustering arguments
    parser_all = subparsers.add_parser('all',
                                       parents=[getCommonArgParser(log=False, failed=False, multiproc=True), parent_parser],
                                       formatter_class=CommonHelpFormatter, add_help=False,
                                       help='Cluster all sequences regardless of annotation.',
                                       description='Cluster all sequences regardless of annotation.')
    group_all = parser_all.add_argument_group('total sequence clustering arguments')
    group_all.add_argument('--start', action='store', dest='seq_start', type=int,
                           help='''The start of the region to be used for clustering.
                                Together with --end, this parameter can be used to specify a
                                subsequence of each read to use in the clustering algorithm.''')
    group_all.add_argument('--end', action='store', dest='seq_end', type=int,
                           help='The end of the region to be used for clustering.')
    parser_all.set_defaults(func=clusterAll)

    # Sequence set clustering arguments
    parser_barcode = subparsers.add_parser('barcode',
                                           parents=[getCommonArgParser(log=False, failed=False, multiproc=True), parent_parser],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='Cluster reads by clustering barcode sequences.',
                                           description='Cluster reads by clustering barcode sequences.')
    group_barcode = parser_barcode.add_argument_group('barcode clustering arguments')
    group_barcode.add_argument('-f', action='store', dest='barcode_field', type=str,
                               default=default_barcode_field,
                               help='''The annotation field containing barcode sequences.''')
    parser_barcode.set_defaults(func=clusterBarcodes)

    return parser


if __name__ == '__main__':
    """
    Parses command line arguments and calls main function
    """
    # Parse arguments
    parser = getArgParser()
    checkArgs(parser)
    args = parser.parse_args()
    args_dict = parseCommonArgs(args)

    # Convert fields to uppercase
    if 'set_field' in args_dict and args_dict['set_field'] is not None:
        args_dict['set_field'] = args_dict['set_field'].upper()
    if 'cluster_field' in args_dict and args_dict['cluster_field'] is not None:
        args_dict['cluster_field'] = args_dict['cluster_field'].upper()

    # Set cluster exec if unspecified
    if args_dict['cluster_exec'] is None:
        args_dict['cluster_exec'] = args_dict['cluster_tool']

    # Check if a valid clustering executable was specified
    if not shutil.which(args_dict['cluster_exec']):
        parser.error('%s executable not found' % args_dict['cluster_exec'])

    # Check for valid start and end input
    if ('seq_start' in args_dict and 'seq_end' in args_dict) and \
            args_dict['seq_start'] is not None and args_dict['seq_end'] is not None and \
            args_dict['seq_start'] >= args_dict['seq_end']:
        parser.error('--start must be less than --end')

    # Call cluster main function for each input file
    del args_dict['seq_files']
    del args_dict['func']
    del args_dict['command']
    if 'out_files' in args_dict:  del args_dict['out_files']
    for i, f in enumerate(args.__dict__['seq_files']):
        args_dict['seq_file'] = f
        args_dict['out_file'] = args.__dict__['out_files'][i] \
            if args.__dict__['out_files'] else None
        args.func(**args_dict)

    # import cProfile
    # prof = cProfile.Profile()
    # results = prof.runcall(args.func, **args_dict)
    # prof.dump_stats('cluster.prof')
