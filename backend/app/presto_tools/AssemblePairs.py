#!D:\project\preprocessing_backend\env\Scripts\python.exe
"""
Assembles paired-end reads into a single sequence
"""
# Info
__author__ = 'Jason Anthony Vander Heiden, Gur Yaari, Christopher Bolen'
from presto import __version__, __date__

# Imports
import os
import shutil
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent

# Presto imports
from presto.Defaults import default_delimiter, choices_coord, \
                            default_coord, default_blastdb_exec, \
                            default_assembly_alpha, default_assembly_max_error, \
                            default_assembly_min_ident, default_assembly_min_len, default_assembly_max_len, \
                            default_assembly_gap, default_assembly_evalue, default_assembly_max_hits, \
                            default_usearch_exec, default_out_args
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.Annotation import parseAnnotation, flattenAnnotation, mergeAnnotation
from presto.Applications import makeBlastnDb, makeUBlastDb
from presto.IO import readReferenceFile, countSeqFile, printLog, printError
from presto.Sequence import reverseComplement, AssemblyStats, \
                            referenceAssembly, joinAssembly, alignAssembly, sequentialAssembly
from presto.Multiprocessing import SeqResult, manageProcesses, \
                                   processSeqQueue, feedPairQueue, collectPairQueue

# Defaults
default_aligner = 'usearch'
default_aligner_exec = default_usearch_exec
choices_aligner = ['blastn', 'usearch']

def assemblyWorker(data, assemble_func, assemble_args={}, rc='tail',
                   fields_1=None, fields_2=None, delimiter=default_delimiter):
    """
    Performs assembly of a sequence pair

    Arguments:
      data : a SeqData object with a list of exactly two SeqRecords.
      assemble_func : the function to use to assemble paired ends.
      assemble_args : a dictionary of arguments to pass to the assembly function.
      rc : Defines which sequences ('head', 'tail', 'both', 'none') to reverse complement
           before assembly; if None do not reverse complement sequences.
      fields_1 : list of annotations in head SeqRecord to copy to assembled record;
                 if None do not copy an annotation.
      fields_2 : list of annotations in tail SeqRecord to copy to assembled record;
                 if None do not copy an annotation.
      delimiter : a tuple of delimiters for (fields, values, value lists).

    Returns:
      SeqResult: a SeqResult object
    """
    # Define result object
    result = SeqResult(data.id, data.data)

    # Reverse complement sequences if required
    head_seq = data.data[0] if rc not in ('head', 'both') \
               else reverseComplement(data.data[0])
    tail_seq = data.data[1] if rc not in ('tail', 'both') \
               else reverseComplement(data.data[1])

    # Define stitched sequence annotation
    stitch_ann = OrderedDict([('ID', data.id)])
    if fields_1 is not None:
        head_ann = parseAnnotation(head_seq.description, fields_1,
                                   delimiter=delimiter)
        stitch_ann = mergeAnnotation(stitch_ann, head_ann, delimiter=delimiter)
        result.log['FIELDS1'] = '|'.join(['%s=%s' % (k, v)
                                             for k, v in head_ann.items()])
    if fields_2 is not None:
        tail_ann = parseAnnotation(tail_seq.description, fields_2,
                                   delimiter=delimiter)
        stitch_ann = mergeAnnotation(stitch_ann, tail_ann, delimiter=delimiter)
        result.log['FIELDS2'] = '|'.join(['%s=%s' % (k, v)
                                             for k, v in tail_ann.items()])

    # Assemble sequences
    stitch = assemble_func(head_seq, tail_seq, **assemble_args)
    ab = stitch.head_pos
    xy = stitch.tail_pos
    result.valid = stitch.valid

    # Add reference to log
    if stitch.ref_seq is not None and stitch.ref_pos is not None:
        result.log['REFID'] = stitch.ref_seq.id
        result.log['REFSEQ'] = ' ' * stitch.ref_pos[0] + stitch.ref_seq.seq

    if ab is not None and xy is not None:
        result.log['SEQ1'] = ' ' * xy[0] + head_seq.seq
        result.log['SEQ2'] = ' ' * ab[0] + tail_seq.seq
    else:
        result.log['SEQ1'] = head_seq.seq
        result.log['SEQ2'] = ' ' * (len(head_seq) + (stitch.gap or 0)) + tail_seq.seq

    # Define stitching log
    if stitch.seq is not None:
        # Update stitch annotation
        stitch.seq.id = flattenAnnotation(stitch_ann, delimiter=delimiter)
        stitch.seq.name = stitch.seq.id
        stitch.seq.description = ''
        result.results = stitch.seq
        # Add assembly to log
        result.log['ASSEMBLY'] = stitch.seq.seq
        if 'phred_quality' in stitch.seq.letter_annotations:
            result.log['QUALITY'] = ''.join([chr(q+33) for q in
                                             stitch.seq.letter_annotations['phred_quality']])
        result.log['LENGTH'] = len(stitch)
        result.log['OVERLAP'] = stitch.overlap
    else:
        result.log['ASSEMBLY'] = None

    # Add mode specific log results
    if stitch.gap is not None:
        result.log['GAP'] = stitch.gap
    if stitch.error is not None:
        result.log['ERROR'] = '%.4f' % stitch.error
    if stitch.pvalue is not None:
        result.log['PVALUE'] = '%.4e' % stitch.pvalue
    if stitch.evalue is not None:
        result.log['EVALUE1'] = '%.4e' % stitch.evalue[0]
        result.log['EVALUE2'] = '%.4e' % stitch.evalue[1]
    if stitch.ident is not None:
        result.log['IDENTITY'] = '%.4f' % stitch.ident

    return result


def assemblePairs(head_file, tail_file, assemble_func, assemble_args={},
                  coord_type=default_coord, rc='tail',
                  head_fields=None, tail_fields=None,
                  out_file=None, out_args=default_out_args,
                  nproc=None, queue_size=None):
    """
    Generates consensus sequences

    Arguments:
      head_file : the head sequence file name
      tail_file : the tail sequence file name
      assemble_func : the function to use to assemble paired ends
      assemble_args : a dictionary of arguments to pass to the assembly function
      coord_type : the sequence header format
      rc : Defines which sequences ('head', 'tail', 'both', 'none') to reverse complement before assembly;
           if 'none' do not reverse complement sequences
      head_fields : list of annotations in head_file records to copy to assembled record;
                    if None do not copy an annotation
      tail_fields : list of annotations in tail_file records to copy to assembled record;
                    if None do not copy an annotation
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs
      nproc = the number of processQueue processes;
              if None defaults to the number of CPUs
      queue_size = maximum size of the argument queue;
                   if None defaults to 2*nproc

    Returns:
      list: a list of successful output file names.
    """
    # Define subcommand label dictionary
    cmd_dict = {alignAssembly: 'align',
                joinAssembly: 'join',
                referenceAssembly: 'reference',
                sequentialAssembly: 'sequential'}
    cmd_name = cmd_dict.get(assemble_func, assemble_func.__name__)

    # Print parameter info
    log = OrderedDict()
    log['START'] = 'AssemblePairs'
    log['COMMAND'] = cmd_name
    log['FILE1'] = os.path.basename(head_file)
    log['FILE2'] = os.path.basename(tail_file)
    log['COORD_TYPE'] = coord_type
    if 'ref_file' in assemble_args:  log['REFFILE'] = assemble_args['ref_file']
    if 'alpha' in assemble_args:  log['ALPHA'] = assemble_args['alpha']
    if 'max_error' in assemble_args:  log['MAX_ERROR'] = assemble_args['max_error']
    if 'min_len' in assemble_args:  log['MIN_LEN'] = assemble_args['min_len']
    if 'max_len' in assemble_args:  log['MAX_LEN'] = assemble_args['max_len']
    if 'scan_reverse' in assemble_args:  log['SCAN_REVERSE'] = assemble_args['scan_reverse']
    if 'gap' in assemble_args:  log['GAP'] = assemble_args['gap']
    if 'min_ident' in assemble_args:  log['MIN_IDENT'] = assemble_args['min_ident']
    if 'evalue' in assemble_args:  log['EVALUE'] = assemble_args['evalue']
    if 'max_hits' in assemble_args:  log['MAX_HITS'] = assemble_args['max_hits']
    if 'fill' in assemble_args:  log['FILL'] = assemble_args['fill']
    if 'aligner' in assemble_args:  log['ALIGNER'] = assemble_args['aligner']
    log['NPROC'] = nproc
    printLog(log)

    # Count input files
    head_count = countSeqFile(head_file)
    tail_count = countSeqFile(tail_file)
    if head_count != tail_count:
        printError('FILE1 (n=%i) and FILE2 (n=%i) must have the same number of records.' \
                 % (head_count, tail_count))

    # Setup reference alignment arguments
    assemble_args = assemble_args.copy()
    if cmd_name in ('reference', 'sequential'):
        ref_file = assemble_args.pop('ref_file')
        db_exec = assemble_args.pop('db_exec')

        # Build reference sequence dictionary
        assemble_args['ref_dict'] = readReferenceFile(ref_file)

        # Build reference database files
        try:
            db_func = {'blastn': makeBlastnDb, 'usearch': makeUBlastDb}[assemble_args['aligner']]
            ref_db, db_handle = db_func(ref_file, db_exec)
            assemble_args['ref_db'] = ref_db
        except ValueError as e:
            printError('Error building reference database for aligner %s with executable %s.' \
                       % (assemble_args['aligner'], db_exec) \
                       +  ' ' + str(e) )
        except:
            printError('Error building reference database for aligner %s with executable %s.' \
                       % (assemble_args['aligner'], db_exec))

    # Define feeder function and arguments
    feed_func = feedPairQueue
    feed_args = {'seq_file_1': head_file,
                 'seq_file_2': tail_file,
                 'coord_type': coord_type,
                 'delimiter': out_args['delimiter']}
    # Define worker function and arguments
    process_args = {'assemble_func': assemble_func,
                    'assemble_args': assemble_args,
                    'rc': rc,
                    'fields_1': head_fields,
                    'fields_2': tail_fields,
                    'delimiter': out_args['delimiter']}
    work_func = processSeqQueue
    work_args = {'process_func': assemblyWorker,
                 'process_args': process_args}
    # Define collector function and arguments
    collect_func = collectPairQueue
    collect_args = {'seq_file_1': head_file,
                    'seq_file_2': tail_file,
                    'label': 'assemble',
                    'out_file': out_file,
                    'out_args': out_args}

    # Call process manager
    result = manageProcesses(feed_func, work_func, collect_func,
                             feed_args, work_args, collect_args,
                             nproc, queue_size)

    # Close reference database handle
    if cmd_name in ('reference', 'sequential'):
        try:
            db_handle.close()
        except AttributeError:
            db_handle.cleanup()
        except:
            printError('Cannot close reference database file.')

    # Print log
    log = OrderedDict()
    log['OUTPUT'] = result['log'].pop('OUTPUT')
    for k, v in result['log'].items():  log[k] = v
    log['END'] = 'AssemblePairs'
    printLog(log)

    return result['out_files']


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
                 assemble-pass
                     successfully assembled reads.
                 assemble-fail
                     raw reads failing paired-end assembly.

             output annotation fields:
                 <user defined>
                     annotation fields specified by the --1f or --2f arguments.
             ''')

    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s %s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', dest='command', metavar='',
                                       help='Assembly method')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Parent parser
    parent_parser = getCommonArgParser(seq_paired=True, multiproc=True)
    group_parser = parent_parser.add_argument_group('format arguments')
    group_parser.add_argument('--coord', action='store', dest='coord_type',
                              choices=choices_coord, default=default_coord,
                              help='''The format of the sequence identifier which defines shared coordinate
                                   information across paired ends.''')
    group_parser.add_argument('--rc', action='store', dest='rc', choices=('tail', 'head', 'both', 'none'),
                              default='tail', help='Specify which read to reverse complement before stitching.')
    group_parser.add_argument('--1f', nargs='+', action='store', dest='head_fields', type=str, default=None,
                              help='Specify annotation fields to copy from head records into assembled record.')
    group_parser.add_argument('--2f', nargs='+', action='store', dest='tail_fields', type=str, default=None,
                              help='Specify annotation fields to copy from tail records into assembled record.')

    # Paired end overlap alignment mode argument parser
    parent_align = ArgumentParser(formatter_class=CommonHelpFormatter, add_help=False)
    group_align = parent_align.add_argument_group('de novo assembly arguments')
    group_align.add_argument('--alpha', action='store', dest='alpha', type=float,
                             default=default_assembly_alpha, help='Significance threshold for de novo paired-end assembly.')
    group_align.add_argument('--maxerror', action='store', dest='max_error', type=float,
                             default=default_assembly_max_error, help='Maximum allowable error rate for de novo assembly.')
    group_align.add_argument('--minlen', action='store', dest='min_len', type=int,
                             default=default_assembly_min_len, help='Minimum sequence length to scan for overlap in de novo assembly.')
    group_align.add_argument('--maxlen', action='store', dest='max_len', type=int,
                             default=default_assembly_max_len, help='Maximum sequence length to scan for overlap in de novo assembly.')
    group_align.add_argument('--scanrev', action='store_true', dest='scan_reverse',
                              help='''If specified, scan past the end of the tail sequence in de novo assembly to allow
                                      the head sequence to overhang the end of the tail sequence.''')
    parser_align = subparsers.add_parser('align', parents=[parent_parser, parent_align], add_help=False,
                                         formatter_class=CommonHelpFormatter,
                                         help='Assemble pairs by aligning ends.',
                                         description='Assemble pairs by aligning ends.')
    parser_align.set_defaults(assemble_func=alignAssembly)

    # Paired end concatenation mode argument parser
    parser_join = subparsers.add_parser('join', parents=[parent_parser],
                                         formatter_class=CommonHelpFormatter, add_help=False,
                                         help='Assemble pairs by concatenating ends.',
                                         description='Assemble pairs by concatenating ends.')
    parser_join.add_argument_group('join assembly arguments').add_argument('--gap', action='store', dest='gap',
                                                                           type=int, default=default_assembly_gap,
                                                                           help='Number of N characters to place between ends.')
    parser_join.set_defaults(assemble_func=joinAssembly)

    # Reference alignment mode argument parser
    parent_ref = ArgumentParser(formatter_class=CommonHelpFormatter, add_help=False)
    group_ref = parent_ref.add_argument_group('reference guided assembly arguments')
    group_ref.add_argument('-r', action='store', dest='ref_file', required=True,
                            help='''A FASTA file containing the reference sequence database.''')
    group_ref.add_argument('--minident', action='store', dest='min_ident', type=float,
                           default=default_assembly_min_ident,
                           help='''Minimum identity of the assembled sequence required to call a
                                 valid reference guided assembly (between 0 and 1).''')
    group_ref.add_argument('--evalue', action='store', dest='evalue', type=float,
                           default=default_assembly_evalue,
                           help='''Minimum E-value for reference alignment for both
                                 the head and tail sequence.''')
    group_ref.add_argument('--maxhits', action='store', dest='max_hits', type=int,
                           default=default_assembly_max_hits,
                           help='''Maximum number of hits from the reference alignment to check for
                                 matching head and tail sequence assignments.''')
    group_ref.add_argument('--fill', action='store_true', dest='fill',
                            help='''Specify to change the behavior of inserted characters when the head and tail
                                 sequences do not overlap during reference guided assembly. If specified,
                                 this will result in inserted of the V region reference sequence
                                 instead of a sequence of Ns in the non-overlapping region.
                                 Warning: you could end up making chimeric sequences by using this option.''')
    group_ref.add_argument('--aligner', action='store', dest='aligner',
                           choices=choices_aligner, default=default_aligner,
                           help='''The local alignment tool to use. Must be one blastn
                                (blast+ nucleotide) or usearch (ublast algorithm).''')
    group_ref.add_argument('--exec', action='store', dest='aligner_exec', default=None,
                           help='''The  name or location of the aligner executable file
                                (blastn or usearch). Defaults to the name specified by the
                                --aligner argument.''')
    group_ref.add_argument('--dbexec', action='store', dest='db_exec', default=None,
                           help='''The  name or location of the executable file that builds
                                the reference database. This defaults to makeblastdb when
                                blastn is specified to the --aligner argument, and usearch
                                when usearch is specified.''')
    parser_ref = subparsers.add_parser('reference', parents=[parent_parser, parent_ref],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Assemble pairs by aligning reads against a reference database.',
                                        description='Assemble pairs by aligning reads against a reference database.')
    parser_ref.set_defaults(assemble_func=referenceAssembly)

    # De novo to reference rollover assembly
    parser_two = subparsers.add_parser('sequential', parents=[parent_parser, parent_align, parent_ref],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Assemble pairs by first attempting de novo assembly, then reference guided assembly.',
                                        description='Assemble pairs by first attempting de novo assembly, then reference guided assembly.')
    parser_two.set_defaults(assemble_func=sequentialAssembly)

    return parser


if __name__ == '__main__':
    """
    Parses command line arguments and calls main function
    """
    # Parse arguments
    parser = getArgParser()
    checkArgs(parser)
    args = parser.parse_args()
    args_dict = parseCommonArgs(args, in_arg='ref_file')

    # Convert case of fields
    if args_dict['head_fields']:  args_dict['head_fields'] = list(map(str.upper, args_dict['head_fields']))
    if args_dict['tail_fields']:  args_dict['tail_fields'] = list(map(str.upper, args_dict['tail_fields']))

    # Define assemble_args dictionary for join mode
    if args_dict['assemble_func'] is joinAssembly:
        args_dict['assemble_args'] = {'gap':args_dict['gap']}
        del args_dict['gap']

    # Define assemble_args dictionary for align mode
    if args_dict['assemble_func'] is alignAssembly or args_dict['assemble_func'] is sequentialAssembly:
        assemble_args = args_dict.setdefault('assemble_args', {})
        assemble_args.update({'alpha': args_dict['alpha'],
                              'max_error': args_dict['max_error'],
                              'min_len': args_dict['min_len'],
                              'max_len': args_dict['max_len'],
                              'scan_reverse': args_dict['scan_reverse'],
                              'assembly_stats': AssemblyStats(args_dict['max_len'] + 1)})
        del args_dict['alpha']
        del args_dict['max_error']
        del args_dict['min_len']
        del args_dict['max_len']
        del args_dict['scan_reverse']

    # Define assemble_args dictionary for reference mode
    if args_dict['assemble_func'] is referenceAssembly or args_dict['assemble_func'] is sequentialAssembly:
        assemble_args = args_dict.setdefault('assemble_args', {})
        assemble_args.update({'ref_file': args_dict['ref_file'],
                              'min_ident': args_dict['min_ident'],
                              'evalue': args_dict['evalue'],
                              'max_hits': args_dict['max_hits'],
                              'fill': args_dict['fill'],
                              'aligner': args_dict['aligner']})
        if args_dict['aligner_exec'] is None:
            assemble_args.update({'aligner_exec': args_dict['aligner']})
        else:
            assemble_args.update({'aligner_exec': args_dict['aligner_exec']})

        if args_dict['db_exec'] is None:
            exec_map = {'blastn': default_blastdb_exec, 'usearch': default_usearch_exec}
            assemble_args.update({'db_exec': exec_map[args_dict['aligner']]})
        else:
            assemble_args.update({'db_exec': args_dict['db_exec']})

        del args_dict['ref_file']
        del args_dict['min_ident']
        del args_dict['evalue']
        del args_dict['max_hits']
        del args_dict['fill']
        del args_dict['aligner']
        del args_dict['aligner_exec']
        del args_dict['db_exec']

        # Check if a valid executable was specified
        if not shutil.which(args_dict['assemble_args']['aligner_exec']):
            parser.error('%s executable not found' % args_dict['assemble_args']['aligner_exec'])

    # Call assemblePairs for each sample file
    del args_dict['command']
    del args_dict['seq_files_1']
    del args_dict['seq_files_2']
    if 'out_files' in args_dict:  del args_dict['out_files']
    for i, (head, tail) in enumerate(zip(args.__dict__['seq_files_1'], args.__dict__['seq_files_2'])):
        args_dict['head_file'] = head
        args_dict['tail_file'] = tail
        args_dict['out_file'] = args.__dict__['out_files'][i] \
            if args.__dict__['out_files'] else None
        assemblePairs(**args_dict)
