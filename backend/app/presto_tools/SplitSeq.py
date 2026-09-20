#!C:\Users\sahar\OneDrive\Desktop\shayesteh\presto-backend\venv\Scripts\python.exe
"""
Sorts, samples and splits FASTA/FASTQ sequence files
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from presto import __version__, __date__

# Imports
import os
import random
import sys
import csv
from argparse import ArgumentParser
from collections import OrderedDict
from operator import xor
from textwrap import dedent
from time import time
from Bio import SeqIO

# Presto imports
from presto.Defaults import choices_coord, default_coord, default_out_args
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.Sequence import indexSeqSets, subsetSeqIndex
from presto.Annotation import parseAnnotation, getAnnotationValues, getCoordKey
from presto.IO import getFileType, readSeqFile, countSeqFile, getOutputHandle, \
                      openFile, printLog, printMessage, printProgress, printCount, printWarning, printError


def downsizeSeqFile(seq_file, max_count, out_args=default_out_args):
    """
    Splits a FASTA/FASTQ file into segments with a limited number of records

    Arguments:
      seq_file : filename of the FASTA file to split
      max_count : number of records in each output file
      out_args : common output argument dictionary from parseCommonArgs

    Returns:
      list: output file names
    """
    log = OrderedDict()
    log['START'] = 'SplitSeq'
    log['COMMAND'] = 'count'
    log['FILE'] = os.path.basename(seq_file)
    log['MAX_COUNT'] = max_count
    printLog(log)

    # Open file handles
    in_type = getFileType(seq_file)
    seq_iter = readSeqFile(seq_file)
    if out_args['out_type'] is None:  out_args['out_type'] = in_type
    # Determine total numbers of records
    rec_count = countSeqFile(seq_file)

    # Loop through iterator writing each record and opening new output handle as needed
    start_time = time()
    seq_count, part_num = 0, 1
    out_handle = getOutputHandle(seq_file, 'part%06i' % part_num, out_dir=out_args['out_dir'],
                                 out_name=out_args['out_name'], out_type=out_args['out_type'],
                                 gzip_output=out_args.get('gzip_output', False))
    out_files = [out_handle.name]
    for seq in seq_iter:
        # Print progress for previous iteration
        printProgress(seq_count, rec_count, 0.05, start_time=start_time)

        # Update count
        seq_count += 1

        # Write records
        SeqIO.write(seq, out_handle, out_args['out_type'])
        # Break if total records reached to avoid extra empty file
        if seq_count == rec_count:
            break

        # Open new file if needed
        if seq_count % max_count == 0:
            out_handle.close()
            part_num += 1
            out_handle = getOutputHandle(seq_file, 'part%06i' % part_num, out_dir=out_args['out_dir'],
                                         out_name=out_args['out_name'], out_type=out_args['out_type'],
                                         gzip_output=out_args.get('gzip_output', False))
            out_files.append(out_handle.name)

    # Print log
    printProgress(seq_count, rec_count, 0.05, start_time=start_time)
    log = OrderedDict()
    for i, f in enumerate(out_files):
        log['OUTPUT%i' % (i + 1)] = os.path.basename(f)
    log['SEQUENCES'] = rec_count
    log['PARTS'] = len(out_files)
    log['END'] = 'SplitSeq'
    printLog(log)

    # Close file handles
    out_handle.close()

    return out_files


def groupSeqFile(seq_file, field, threshold=None, out_args=default_out_args):
    """
    Divides a sequence file into segments by description tags

    Arguments:
      seq_file : filename of the sequence file to split
      field : The annotation field to split seq_file by
      threshold : The numerical threshold for group sequences by;
                  if None treat field as textual
      out_args : common output argument dictionary from parseCommonArgs

    Returns:
      list: output file names
    """
    log = OrderedDict()
    log['START'] = 'SplitSeq'
    log['COMMAND'] = 'group'
    log['FILE'] = os.path.basename(seq_file)
    log['FIELD'] = field
    log['THRESHOLD'] = threshold
    printLog(log)

    # Open file handles
    in_type = getFileType(seq_file)
    seq_iter = readSeqFile(seq_file)
    if out_args['out_type'] is None:  out_args['out_type'] = in_type

    # Determine total numbers of records
    rec_count = countSeqFile(seq_file)

    # Process sequences
    start_time = time()
    seq_count = 0
    if threshold is None:
        # Sort records into files based on textual field
        # Create set of unique field tags
        temp_iter = readSeqFile(seq_file)
        tag_list = getAnnotationValues(temp_iter, field, unique=True, delimiter=out_args['delimiter'])

        if sys.platform != 'win32':
            import resource
            # Increase open file handle limit if needed
            file_limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0]
            file_count = len(tag_list) + 256
            if file_limit < file_count and file_count <= 8192:
                #print file_limit, file_count
                resource.setrlimit(resource.RLIMIT_NOFILE, (file_count, file_count))
            elif file_count > 8192:
                e = '''OS file limit would need to be set to %i.
                    If you are sure you want to do this, then increase the
                    file limit in the OS (via ulimit) and rerun this tool.
                    ''' % file_count
                printError(dedent(e))

        # Create output handles
        # out_label = '%s=%s' % (field, tag)
        handles_dict = {tag:getOutputHandle(seq_file,
                                            '%s-%s' % (field, tag),
                                            out_dir=out_args['out_dir'],
                                            out_name=out_args['out_name'],
                                            out_type=out_args['out_type'],
                                            gzip_output=out_args.get('gzip_output', False))
                        for tag in tag_list}

        # Iterate over sequences
        for seq in seq_iter:
            printProgress(seq_count, rec_count, 0.05, start_time=start_time)
            seq_count += 1
            # Write sequences
            tag = parseAnnotation(seq.description, delimiter=out_args['delimiter'])[field]
            SeqIO.write(seq, handles_dict[tag], out_args['out_type'])
    else:
        # Sort records into files based on numeric threshold
        threshold = float(threshold)
        # Create output handles
        handles_dict = {'under':getOutputHandle(seq_file,
                                                'under-%.1g' % threshold,
                                                out_dir=out_args['out_dir'],
                                                out_name=out_args['out_name'],
                                                out_type=out_args['out_type'],
                                                gzip_output=out_args.get('gzip_output', False)),
                        'atleast':getOutputHandle(seq_file,
                                                  'atleast-%.1g' % threshold,
                                                  out_dir=out_args['out_dir'],
                                                  out_name=out_args['out_name'],
                                                  out_type=out_args['out_type'],
                                                  gzip_output=out_args.get('gzip_output', False))}

        # Iterate over sequences
        for seq in seq_iter:
            printProgress(seq_count, rec_count, 0.05, start_time=start_time)
            seq_count += 1
            # Write sequences
            tag = parseAnnotation(seq.description, delimiter=out_args['delimiter'])[field]
            tag = 'under' if float(tag) < threshold else 'atleast'
            SeqIO.write(seq, handles_dict[tag], out_args['out_type'])

    # Print log
    printProgress(seq_count, rec_count, 0.05, start_time=start_time)
    log = OrderedDict()
    for i, k in enumerate(handles_dict):
        log['OUTPUT%i' % (i + 1)] = os.path.basename(handles_dict[k].name)
    log['SEQUENCES'] = rec_count
    log['PARTS'] = len(handles_dict)
    log['END'] = 'SplitSeq'
    printLog(log)

    # Close output file handles
    for k in handles_dict: handles_dict[k].close()

    return [handles_dict[k].name for k in handles_dict]


def sampleSeqFile(seq_file, max_count, field=None, values=None, out_args=default_out_args):
    """
    Samples from a sequence file

    Arguments:
      seq_file : filename of the sequence file to sample from
      max_count : a list of the maximum number of sequences to sample
      field : the annotation field to check for required values
      values : a list of annotation values that a sample must contain one of
      out_args : common output argument dictionary from parseCommonArgs

    Returns:
      str: output file name
    """
    # Function to sample from a list of sequence indices
    def _sample_list(n, index_list):
        max_n = len(index_list)
        r = random.sample(range(max_n), n) if n < max_n else range(max_n)
        return [index_list[x] for x in r]

    # Function to sample from a dictionary of grouped sequence indices
    def _sample_dict(n, index_dict):
        sample_list = []
        for v in index_dict.values():
            max_n = len(v)
            r = random.sample(range(max_n), n) if n < max_n else range(max_n)
            sample_list.extend([v[x] for x in r])
        return sample_list

    # Print console log
    log = OrderedDict()
    log['START'] = 'SplitSeq'
    log['COMMAND'] = 'sample'
    log['FILE'] = os.path.basename(seq_file)
    log['MAX_COUNTS'] = ','.join([str(x) for x in max_count])
    log['FIELD'] = field
    log['VALUES'] = ','.join(values) if values else None
    printLog(log)

    # Read input files and open output files
    start_time = time()
    printMessage('Reading files', start_time=start_time, width=25)

    in_type = getFileType(seq_file)
    seq_dict = readSeqFile(seq_file, index=True)
    if out_args['out_type'] is None:  out_args['out_type'] = in_type

    # Generate subset of records
    if field is not None and values is not None:
        _sample = _sample_list
        printMessage('Subsetting by annotation', start_time=start_time, width=25)
        seq_index = subsetSeqIndex(seq_dict, field, values, delimiter=out_args['delimiter'])
    elif field is not None and values is None:
        _sample = _sample_dict
        printMessage('Indexing by annotation', start_time=start_time, width=25)
        seq_index = indexSeqSets(seq_dict, field, delimiter=out_args['delimiter'])
    else:
        _sample = _sample_list
        seq_index = [k for k in seq_dict]

    printMessage('Done', start_time=start_time, end=True, width=25)

    # Generate sample set for each value in max_count
    out_files = []
    for i, n in enumerate(max_count):
        start_time = time()
        printMessage('Sampling n=%i' % n, start_time=start_time, width=25)
        # Sample from records
        sample_keys = _sample(n, seq_index)
        sample_count = len(sample_keys)

        # Write sampled sequences to files
        with getOutputHandle(seq_file,
                             'sample%i-n%i' % (i + 1, sample_count),
                             out_dir=out_args['out_dir'],
                             out_name=out_args['out_name'],
                             out_type=out_args['out_type'],
                             gzip_output=out_args.get('gzip_output', False)) as out_handle:
            for k in sample_keys:
                SeqIO.write(seq_dict[k], out_handle, out_args['out_type'])
            out_files.append(out_handle.name)

        printMessage('Done', start_time=start_time, end=True, width=25)

        # Print log for iteration
        log = OrderedDict()
        log['MAX_COUNT'] = n
        log['SAMPLED'] = sample_count
        log['OUTPUT'] = os.path.basename(out_files[i])
        printLog(log)



    # Print log
    log = OrderedDict()
    log['END'] = 'SplitSeq'
    printLog(log)

    return out_files


def samplePairSeqFile(seq_file_1, seq_file_2, max_count, field=None, values=None,
                      coord_type=default_coord, out_args=default_out_args):
    """
    Samples from paired-end sequence files

    Arguments:
      seq_file_1 : filename of the first paired-end sequence file
      seq_file_2 : filename of the second paired-end sequence file
      max_count : a list of the maximum number of sequences to sample
      field : the annotation field to check for required values
      values : a list of annotation values that a sample must contain one of
      coord_type : the sequence header format
      out_args : common output argument dictionary from parseCommonArgs

    Returns:
      list: seq_file_1 and seq_file_2 output file names
    """
    # Sequence index key function
    def _key_func(x):
        return getCoordKey(x, coord_type=coord_type, delimiter=out_args['delimiter'])

    # Function to sample from two lists of sequence indices
    def _sample_list(n, index_1, index_2):
        key_set = set(index_1).intersection(index_2)
        max_n = len(key_set)
        return random.sample(list(key_set), min(n, max_n))

    # Function to sample from two dictionaries of grouped sequence indices
    def _sample_dict(n, index_1, index_2):
        group_set = set(index_1.keys()).intersection(index_2.keys())
        sample_list = []
        for k in group_set:
            key_set = set(index_1[k]).intersection(index_2[k])
            max_n = len(key_set)
            sample_list.extend(random.sample(list(key_set), min(n, max_n)))
        return sample_list

    # Print console log
    log = OrderedDict()
    log['START']= 'SplitSeq'
    log['COMMAND'] = 'samplepair'
    log['FILE1'] = os.path.basename(seq_file_1)
    log['FILE2'] = os.path.basename(seq_file_2)
    log['MAX_COUNTS'] = ','.join([str(x) for x in max_count])
    log['FIELD'] = field
    log['VALUES'] = ','.join(values) if values else None
    printLog(log)

    # Define output type
    in_type_1 = getFileType(seq_file_1)
    in_type_2 = getFileType(seq_file_2)
    if out_args['out_type'] is None:
        out_type_1 = in_type_1
        out_type_2 = in_type_2
    else:
        out_type_1 = out_type_2 = out_args['out_type']

    # Define output name
    if out_args['out_name'] is None:
        out_name_1 = out_name_2 = None
    else:
        out_name_1 = '%s-1' % out_args['out_name']
        out_name_2 = '%s-2' % out_args['out_name']

    # Index input files
    start_time = time()
    printMessage('Reading files', start_time=start_time, width=25)

    seq_dict_1 = readSeqFile(seq_file_1, index=True, key_func=_key_func)
    seq_dict_2 = readSeqFile(seq_file_2, index=True, key_func=_key_func)

    # Subset keys to those meeting field/value criteria
    if field is not None and values is not None:
        _sample = _sample_list
        printMessage('Subsetting by annotation', start_time=start_time, width=25)
        seq_index_1 = subsetSeqIndex(seq_dict_1, field, values,
                                     delimiter=out_args['delimiter'])
        seq_index_2 = subsetSeqIndex(seq_dict_2, field, values,
                                     delimiter=out_args['delimiter'])
    elif field is not None and values is None:
        _sample = _sample_dict
        printMessage('Indexing by annotation', start_time=start_time, width=25)
        seq_index_1 = indexSeqSets(seq_dict_1, field, delimiter=out_args['delimiter'])
        seq_index_2 = indexSeqSets(seq_dict_2, field, delimiter=out_args['delimiter'])
    else:
        _sample = _sample_list
        seq_index_1 = list(seq_dict_1.keys())
        seq_index_2 = list(seq_dict_2.keys())

    printMessage('Done', start_time=start_time, end=True, width=25)

    # Generate sample set for each value in max_count
    out_files = []
    for i, n in enumerate(max_count):
        start_time = time()
        printMessage('Sampling n=%i' % n, start_time=start_time, width=25)
        # Sample
        sample_keys = _sample(n, seq_index_1, seq_index_2)
        sample_count = len(sample_keys)

        # Open file handles
        out_handle_1 = getOutputHandle(seq_file_1,
                                       'sample%i-n%i' % (i + 1, sample_count),
                                       out_dir=out_args['out_dir'],
                                       out_name=out_name_1,
                                       out_type=out_type_1,
                                       gzip_output=out_args.get('gzip_output', False))
        out_handle_2 = getOutputHandle(seq_file_2,
                                       'sample%i-n%i' % (i + 1, sample_count),
                                       out_dir=out_args['out_dir'],
                                       out_name=out_name_2,
                                       out_type=out_type_2,
                                       gzip_output=out_args.get('gzip_output', False))
        out_files.append((out_handle_1.name, out_handle_2.name))

        for k in sample_keys:
            SeqIO.write(seq_dict_1[k], out_handle_1, out_type_1)
            SeqIO.write(seq_dict_2[k], out_handle_2, out_type_2)

        printMessage('Done', start_time=start_time, end=True, width=25)

        # Print log for iteration
        log = OrderedDict()
        log['MAX_COUNT'] = n
        log['SAMPLED'] = sample_count
        log['OUTPUT1'] = os.path.basename(out_files[i][0])
        log['OUTPUT2'] = os.path.basename(out_files[i][1])
        printLog(log)

        # Close file handles
        out_handle_1.close()
        out_handle_2.close()

    # Print log
    log = OrderedDict()
    log['END'] = 'SplitSeq'
    printLog(log)

    return out_files


def sortSeqFile(seq_file, field, numeric=False, max_count=None, out_args=default_out_args):
    """
    Sorts a sequence file by annotation fields

    Arguments:
      seq_file : filename of the sequence file to split
      field : position of field in sequence description to split by
      numeric : if True sort field numerically;
                if False sort field alphabetically
      max_count : maximum number of records in each output file
                  if None do not create multiple files
      out_args : common output argument dictionary from parseCommonArgs

    Returns:
      list: output file names
    """
    log = OrderedDict()
    log['START'] = 'SplitSeq'
    log['COMMAND'] = 'sort'
    log['FILE'] = os.path.basename(seq_file)
    log['FIELD'] = field
    log['NUMERIC'] = numeric
    log['MAX_COUNT'] = max_count
    printLog(log)

    # Open file handles
    in_type = getFileType(seq_file)
    seq_dict = readSeqFile(seq_file, index=True)
    if out_args['out_type'] is None:  out_args['out_type'] = in_type

    # Get annotations and sort seq_dict by annotation values
    tag_dict = {k:parseAnnotation(seq_dict[k].description, delimiter=out_args['delimiter'])[field]
                for k in seq_dict}
    if numeric:  tag_dict = {k:float(v or 0) for k, v in tag_dict.items()}
    sorted_keys = sorted(tag_dict, key=tag_dict.get)

    # Determine total numbers of records
    rec_count = len(seq_dict)
    if max_count is not None and max_count >= rec_count:  max_count = None

    # Open initial output file handles
    file_count = 1
    if max_count is None:  out_label = 'sorted'
    else:  out_label = 'sorted-part%06i' % file_count
    out_handle = getOutputHandle(seq_file,
                                 out_label,
                                 out_dir=out_args['out_dir'],
                                 out_name=out_args['out_name'],
                                 out_type=out_args['out_type'],
                                 gzip_output=out_args.get('gzip_output', False))
    out_files = [out_handle.name]

    # Loop through sorted sequence dictionary keys
    start_time = time()
    last_tag = None
    saved_keys = []
    seq_count = chunk_count = 0
    for key in sorted_keys:
        # Print progress for previous iteration and update count
        printProgress(seq_count, rec_count, 0.05, start_time=start_time)
        seq_count += 1

        # Write saved group of sequences when tag changes
        if last_tag is not None and tag_dict[key] != last_tag:
            # Open new output file if needed
            if max_count is not None and chunk_count + len(saved_keys) > max_count:
                # Update partition counts
                file_count += 1
                chunk_count = 0
                # Open new file handle
                out_handle.close()
                out_handle = getOutputHandle(seq_file,
                                             'sorted-part%06i' % file_count,
                                             out_dir=out_args['out_dir'],
                                             out_name=out_args['out_name'],
                                             out_type=out_args['out_type'],
                                             gzip_output=out_args.get('gzip_output', False))
                # Append output file name to out_files
                out_files.append(out_handle.name)

            # Write saved sequences
            for k in saved_keys:
                chunk_count += 1
                SeqIO.write(seq_dict[k], out_handle, out_args['out_type'])
            # Reset saved keys to current key only
            saved_keys = [key]
        else:
            # Update list of saved keys if tag is unchanged
            saved_keys.append(key)

        # Check if total records reached, write all saved keys, and exit loop
        if seq_count == rec_count:
            for k in saved_keys:
                chunk_count += 1
                SeqIO.write(seq_dict[k], out_handle, out_args['out_type'])
            out_handle.close()
            break

        # Update tag tracker
        last_tag = tag_dict[key]

    # Print log
    printProgress(seq_count, rec_count, 0.05, start_time=start_time)
    log = OrderedDict()
    for i, f in enumerate(out_files):
        log['OUTPUT%i' % (i + 1)] = os.path.basename(f)
    log['SEQUENCES'] = seq_count
    log['PARTS'] = len(out_files)
    log['END'] = 'SplitSeq'
    printLog(log)

    # Close file handles
    out_handle.close()

    return out_files


def selectSeqFile(seq_file, field, value_list=None, value_file=None, negate=False,
                  out_file=None, out_args=default_out_args):
    """
    Select from a sequence file

    Arguments:
      seq_file : filename of the sequence file to sample from.
      field : the annotation field to check for required values.
      value_list : a list of annotation values that a sample must contain one of.
      value_file : a tab delimited file containing values to select.
      negate : if True select entires that do not contain the specific values.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      str: output file name.
    """
    # Reads value_file
    def _read_file(value_file, field):
        field_list = []
        try:
            with open(value_file, 'rt') as handle:
                reader_dict = csv.DictReader(handle, dialect='excel-tab')
                for row in reader_dict:
                    field_list.append(row[field])
        except IOError:
            printError('File %s cannot be read.' % value_file)
        except:
            printError('File %s is invalid.' % value_file)

        return field_list

    # Print console log
    log = OrderedDict()
    log['START'] = 'SplitSeq'
    log['COMMAND'] = 'select'
    log['FILE'] = os.path.basename(seq_file)
    log['FIELD'] = field
    if value_list is not None:
        log['VALUE_LIST'] = ','.join([str(x) for x in value_list])
    if value_file is not None:
        log['VALUE_FILE'] = os.path.basename(value_file)
    log['NOT'] = negate
    printLog(log)

    # Read value_file
    if value_list is not None and value_file is not None:
        printError('Specify only one of value_list and value_file.')
    elif value_file is not None:
        value_list = _read_file(value_file, field)

    # Read sequence file
    in_type = getFileType(seq_file)
    seq_iter = readSeqFile(seq_file)
    if out_args['out_type'] is None:  out_args['out_type'] = in_type

    # Output output handle
    if out_file is not None:
        # For explicit output files, check if gzip is needed
        if out_args.get('gzip_output', False) and not out_file.endswith('.gz'):
            out_file = out_file + '.gz'
        out_handle = openFile(out_file, 'w')
    else:
        out_handle = getOutputHandle(seq_file, 'selected',
                                     out_dir=out_args['out_dir'],
                                     out_name=out_args['out_name'],
                                     out_type=out_args['out_type'],
                                     gzip_output=out_args.get('gzip_output', False))

#    try:
    # Generate subset of records
    start_time = time()
    pass_count, fail_count, rec_count = 0, 0, 0
    value_set = set(value_list)
    for rec in seq_iter:
        printCount(rec_count, 1e5, start_time=start_time)
        rec_count += 1

        # Parse annotations into a list of values
        ann = parseAnnotation(rec.description, delimiter=out_args['delimiter'])[field]
        ann = ann.split(out_args['delimiter'][2])

        # Write
        if xor(negate, not value_set.isdisjoint(ann)):
            # Write
            SeqIO.write(rec, out_handle, out_args['out_type'])
            pass_count += 1
        else:
            fail_count += 1

    printCount(rec_count, 1e5, start_time=start_time, end=True)

    # Print log
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(out_handle.name)
    log['PASS'] = pass_count
    log['FAIL'] = fail_count
    log['END'] = 'SplitSeq'
    printLog(log)

    return out_handle.name


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
                 part<part>
                     reads partitioned by count, where <part> is the partition number.
                 <field>-<value>
                     reads partitioned by annotation <field> and <value>.
                 under-<number>
                     reads partitioned by numeric threshold where the annotation value is
                     strictly less than the threshold <number>.
                 atleast-<number>
                     reads partitioned by numeric threshold where the annotation value is
                     greater than or equal to the threshold <number>.
                 sorted
                     reads sorted by annotation value.
                 sorted-part<part>
                     reads sorted by annotation value and partitioned by count, where
                     <part> is the partition number.
                 sample<i>-n<count>
                     randomly sampled reads where <i> is a number specifying the sampling
                     instance and <count> is the number of sampled reads.
                 selected
                     reads passing selection criteria.

             output annotation fields:
                 None
             ''')

    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s %s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', dest='command', metavar='',
                                       help='Sequence file operation')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Subparser to downsize files to a maximum count
    parser_downsize = subparsers.add_parser('count',
                                            parents=[getCommonArgParser(failed=False, out_file=False, annotation=False, log=False)],
                                            formatter_class=CommonHelpFormatter, add_help=False,
                                            help='Splits sequences files by number of records.',
                                            description='Splits sequences files by number of records.')
    group_downsize = parser_downsize.add_argument_group('splitting arguments')
    group_downsize.add_argument('-n', action='store', dest='max_count', type=int, required=True,
                                help='Maximum number of sequences in each new file')
    parser_downsize.set_defaults(func=downsizeSeqFile)

    # Subparser to partition files by annotation
    parser_group = subparsers.add_parser('group',
                                         parents=[getCommonArgParser(failed=False, out_file=False, log=False)],
                                         formatter_class=CommonHelpFormatter, add_help=False,
                                         help='Splits sequences files by annotation.',
                                         description='Splits sequences files by annotation.')
    group_group = parser_group.add_argument_group('splitting arguments')
    group_group.add_argument('-f', action='store', dest='field', type=str, required=True,
                             help='Annotation field to split sequence files by')
    group_group.add_argument('--num', action='store', dest='threshold', type=float, default=None,
                             help='''Specify to define the split field as numeric and group
                                  sequences by value.''')
    parser_group.set_defaults(func=groupSeqFile)

    # Subparser to randomly sample from unpaired files
    parser_sample = subparsers.add_parser('sample',
                                          parents=[getCommonArgParser(failed=False, out_file=False, log=False)],
                                          formatter_class=CommonHelpFormatter, add_help=False,
                                          help='Randomly samples from unpaired sequences files.',
                                          description='Randomly samples from unpaired sequences files.')
    group_sample = parser_sample.add_argument_group('splitting arguments')
    group_sample.add_argument('-n', nargs='+', action='store', dest='max_count', type=int, required=True,
                              help='''Maximum number of sequences to sample from each file, field or
                                   annotation set. The default behavior, without the -f argument, is to
                                   sample from the complete set of sequences in the input file.''')
    group_sample.add_argument('-f', action='store', dest='field', type=str, default=None,
                              help='''The annotation field for sampling criteria. If the -u argument
                                   is not also specified, then sampling will be performed for each unique
                                   annotation value in the declared field separately.''')
    group_sample.add_argument('-u', nargs='+', action='store', dest='values', type=str, default=None,
                              help='''If specified, sampling will be restricted to sequences that contain
                                   one of the declared annotation values in the specified field.
                                   Requires the -f argument.''')
    parser_sample.set_defaults(func=sampleSeqFile)

    # Subparser to randomly sample from paired files
    parser_sampair = subparsers.add_parser('samplepair',
                                           parents=[getCommonArgParser(failed=False, out_file=False, seq_paired=True, log=False)],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='Randomly samples from paired-end sequences files.',
                                           description='Randomly samples from paired-end sequences files.')
    group_sampair = parser_sampair.add_argument_group('sampling arguments')
    group_sampair.add_argument('-n', nargs='+', action='store', dest='max_count', type=int,  required=True,
                               help='''Maximum number of paired sequences to sample from each
                                    set of files, fields or annotations. The default behavior,
                                    without the -f argument, is to sample from the complete
                                    set of paired sequences in the input files.''')
    group_sampair.add_argument('-f', action='store', dest='field', type=str, default=None,
                               help='''The annotation field for sampling criteria. If the -u argument
                                    is not also specified, then sampling will be performed for each unique
                                    annotation value in the declared field separately.''')
    group_sampair.add_argument('-u', nargs='+', action='store', dest='values', type=str, default=None,
                               help='''If specified, sampling will be restricted to sequences that contain
                                    one of the declared annotation values in the specified field.
                                    Requires the -f argument.''')
    group_sampair.add_argument('--coord', action='store', dest='coord_type',
                               choices=choices_coord, default=default_coord,
                               help='''The format of the sequence identifier which defines shared
                                    coordinate information across paired read files.''')
    parser_sampair.set_defaults(func=samplePairSeqFile)

    # Subparser to sort files
    parser_sort = subparsers.add_parser('sort',
                                        parents=[getCommonArgParser(failed=False, out_file=False, log=False)],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Sorts sequences files by annotation.',
                                        description='Sorts sequences files by annotation.')
    group_sort = parser_sort.add_argument_group('sorting arguments')
    group_sort.add_argument('-f', action='store', dest='field', type=str, required=True,
                            help='The annotation field to sort sequences by.')
    group_sort.add_argument('-n', action='store', dest='max_count', type=int,
                            default=None, help='Maximum number of sequences in each new file.')
    group_sort.add_argument('--num', action='store_true', dest='numeric',
                            help='Specify to define the sort field as numeric rather than textual.')
    parser_sort.set_defaults(func=sortSeqFile)

    # Subparser to select sequences
    parser_select = subparsers.add_parser('select',
                                          parents=[getCommonArgParser(failed=False, log=False)],
                                          formatter_class=CommonHelpFormatter, add_help=False,
                                          help='''Selects sequences from sequence files by annotation.''',
                                          description='''Selects sequences from sequence files by annotation.''')
    group_select = parser_select.add_argument_group('splitting arguments')
    group_select.add_argument('-f', action='store', dest='field', type=str, default=None, required=True,
                               help='''The annotation field for selection criteria.''')
    group_select_val = group_select.add_mutually_exclusive_group()
    group_select_val.add_argument('-u', nargs='+', action='store', dest='value_list', type=str, default=None, required=False,
                                  help='''A list of values to select for in the specified field. Mutually exclusive with -t.''')
    group_select_val.add_argument('-t', action='store', dest='value_file', type=str, default=None, required=False,
                                  help='''A tab delimited file specifying values to select for in the specified field.
                                       The file must be formatted with the given field name in the header row. Values will
                                       be taken from that column. Mutually exclusive with -u.''')
    group_select.add_argument('--not', action='store_true', dest='negate',
                              help='''If specified, will perform negative matching. Meaning, sequences will be selected
                                   if they fail to match for all specified values.''')
    parser_select.set_defaults(func=selectSeqFile)

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
    # Convert case of fields
    if 'field' in args_dict and args_dict['field']:
        args_dict['field'] = args_dict['field'].upper()

    # Check if a valid option was specific for sample mode
    if (args.command == 'sample' or args.command == 'samplepair') and \
       (args.values and not args.field):
            parser.error('Sampling modes requires -f to be specified with -u.')

    # Clean arguments dictionary
    del args_dict['command']
    del args_dict['func']
    if 'out_files' in args_dict:  del args_dict['out_files']

    # Call appropriate function for each sample file
    if 'seq_files' in args_dict:
        del args_dict['seq_files']
        for i, f in enumerate(args.__dict__['seq_files']):
            args_dict['seq_file'] = f
            if 'out_files' in args.__dict__:
                args_dict['out_file'] = args.__dict__['out_files'][i] \
                    if args.__dict__['out_files'] else None
            args.func(**args_dict)
    elif 'seq_files_1' in args_dict and 'seq_files_2' in args_dict:
        del args_dict['seq_files_1']
        del args_dict['seq_files_2']
        for i, (file_1, file_2) in enumerate(zip(args.__dict__['seq_files_1'], args.__dict__['seq_files_2'])):
            args_dict['seq_file_1'] = file_1
            args_dict['seq_file_2'] = file_2
            if 'out_files' in args.__dict__:
                args_dict['out_file'] = args.__dict__['out_files'][i] \
                    if args.__dict__['out_files'] else None
            args.func(**args_dict)
