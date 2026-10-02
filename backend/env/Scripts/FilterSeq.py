#!E:\AIRR-Preprocessing\Preprocessing-code\git\backend\env\Scripts\python.exe
"""
Filters sequences in FASTA/FASTQ files
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from presto import __version__, __date__

# Imports
import os
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent

# Presto imports
from presto.Defaults import default_out_args, default_filter_min_qual, \
                            default_filter_min_len, default_filter_max_missing, \
                            default_filter_max_repeat, default_filter_window
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.IO import getFileType, printLog, printError
from presto.Multiprocessing import manageProcesses, feedSeqQueue, \
                                   processSeqQueue, collectSeqQueue
from presto.Sequence import filterLength, filterMissing, filterRepeats, filterQuality, \
                            trimQuality, maskQuality


def filterSeq(seq_file, filter_func, filter_args={},
              out_file=None, out_args=default_out_args,
              nproc=None, queue_size=None):
    """
    Filters sequences by fraction of ambiguous nucleotides

    Arguments:
      seq_file : the sequence file to filter.
      filter_func : the function to use for filtering sequences.
      filter_args : a dictionary of arguments to pass to filter_func.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.
      nproc : the number of processQueue processes;
              if None defaults to the number of CPUs.
      queue_size : maximum size of the argument queue;
                   if None defaults to 2*nproc.

    Returns:
      list: a list of successful output file names
    """
    # Define output file label dictionary
    cmd_dict = {filterLength: 'length', filterMissing: 'missing',
                filterRepeats: 'repeats', filterQuality: 'quality',
                maskQuality: 'maskqual', trimQuality: 'trimqual'}

    # Print parameter info
    log = OrderedDict()
    log['START'] = 'FilterSeq'
    log['COMMAND'] = cmd_dict.get(filter_func, filter_func.__name__)
    log['FILE'] = os.path.basename(seq_file)
    for k in sorted(filter_args):  log[k.upper()] = filter_args[k]
    log['NPROC'] = nproc
    printLog(log)

    # Check input type
    in_type = getFileType(seq_file)
    if in_type != 'fastq' and filter_func in (filterQuality, maskQuality, trimQuality):
        printError('Input file must be FASTQ for %s mode.' % cmd_dict[filter_func])

    # Define feeder function and arguments
    feed_func = feedSeqQueue
    feed_args = {'seq_file': seq_file}
    # Define worker function and arguments
    work_func = processSeqQueue
    work_args = {'process_func': filter_func,
                 'process_args': filter_args}
    # Define collector function and arguments
    collect_func = collectSeqQueue
    collect_args = {'seq_file': seq_file,
                    'label': cmd_dict[filter_func],
                    'out_file': out_file,
                    'out_args': out_args}

    # Call process manager
    result = manageProcesses(feed_func, work_func, collect_func,
                             feed_args, work_args, collect_args,
                             nproc, queue_size)

    # Print log
    result['log']['END'] = 'FilterSeq'
    printLog(result['log'])

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
                 <command>-pass
                     reads passing filtering operation and modified accordingly, where
                     <command> is the name of the filtering operation that was run.
                 <command>-fail
                     raw reads failing filtering criteria, where <command> is the name of
                     the filtering operation.

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
    subparsers = parser.add_subparsers(title='subcommands', metavar='',
                                       help='Filtering operation')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Parent parser
    parser_parent = getCommonArgParser(annotation=False, log=True, multiproc=True)

    # Length filter mode argument parser
    parser_length = subparsers.add_parser('length', parents=[parser_parent],
                                          formatter_class=CommonHelpFormatter, add_help=False,
                                          help='Filters reads by length.',
                                          description='Filters reads by length.')
    group_length = parser_length.add_argument_group('filtering arguments')
    group_length.add_argument('-n', action='store', dest='min_length', type=int,
                              default=default_filter_min_len,
                              help='Minimum sequence length to retain.')
    group_length.add_argument('--inner', action='store_true', dest='inner',
                               help='''If specified exclude consecutive missing characters
                                    at either end of the sequence.''')
    parser_length.set_defaults(filter_func=filterLength)

    # Missing character filter mode argument parser
    parser_missing = subparsers.add_parser('missing', parents=[parser_parent],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='Filters reads by N or gap character count.',
                                           description='Filters reads by N or gap character count.')
    group_missing = parser_missing.add_argument_group('filtering arguments')
    group_missing.add_argument('-n', action='store', dest='max_missing', type=int,
                               default=default_filter_max_missing,
                               help='Threshold for fraction of gap or N nucleotides.')
    group_missing.add_argument('--inner', action='store_true', dest='inner',
                                help='''If specified exclude consecutive missing characters
                                     at either end of the sequence.''')
    parser_missing.set_defaults(filter_func=filterMissing)

    # Continuous repeating character filter mode argument parser
    parser_repeats = subparsers.add_parser('repeats', parents=[parser_parent],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='Filters reads by consecutive nucleotide repeats.',
                                           description='Filters reads by consecutive nucleotide repeats.')
    group_repeats = parser_repeats.add_argument_group('filtering arguments')
    group_repeats.add_argument('-n', action='store', dest='max_repeat', type=int,
                               default=default_filter_max_repeat,
                               help='Threshold for fraction of repeating nucleotides.')
    group_repeats.add_argument('--missing', action='store_true', dest='include_missing',
                               help='''If specified count consecutive gap and N characters '
                                    in addition to {A,C,G,T}.''')
    group_repeats.add_argument('--inner', action='store_true', dest='inner',
                               help='''If specified exclude consecutive missing characters
                                    at either end of the sequence.''')
    parser_repeats.set_defaults(filter_func=filterRepeats)

    # Quality filter mode argument parser
    parser_quality = subparsers.add_parser('quality', parents=[parser_parent],
                                          formatter_class=CommonHelpFormatter, add_help=False,
                                          help='Filters reads by quality score.',
                                          description='Filters reads by quality score.')
    group_quality = parser_quality.add_argument_group('filtering arguments')
    group_quality.add_argument('-q', action='store', dest='min_qual', type=float,
                               default=default_filter_min_qual, help='Quality score threshold.')
    group_quality.add_argument('--inner', action='store_true', dest='inner',
                               help='''If specified exclude consecutive missing characters
                                    at either end of the sequence.''')
    parser_quality.set_defaults(filter_func=filterQuality)

    # Mask mode argument parser
    parser_maskqual = subparsers.add_parser('maskqual', parents=[parser_parent],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Masks low quality positions.',
                                        description='Masks low quality positions.')
    group_maskqual = parser_maskqual.add_argument_group('filtering arguments')
    group_maskqual.add_argument('-q', action='store', dest='min_qual', type=float,
                                default=default_filter_min_qual, help='Quality score threshold.')
    parser_maskqual.set_defaults(filter_func=maskQuality)

    # Trim mode argument parser
    parser_trimqual = subparsers.add_parser('trimqual', parents=[parser_parent],
                                            formatter_class=CommonHelpFormatter, add_help=False,
                                            help='Trims sequences by quality score decay.',
                                            description='Trims sequences by quality score decay.')
    group_trimqual = parser_trimqual.add_argument_group('filtering arguments')
    group_trimqual.add_argument('-q', action='store', dest='min_qual', type=float,
                                default=default_filter_min_qual, help='Quality score threshold.')
    group_trimqual.add_argument('--win', action='store', dest='window', type=int,
                                default=default_filter_window,
                                help='Nucleotide window size for moving average calculation.')
    group_trimqual.add_argument('--reverse', action='store_true', dest='reverse',
                                help='''Specify to trim the head of the sequence rather
                                     than the tail.''')
    parser_trimqual.set_defaults(filter_func=trimQuality)

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

    # Create filter_args
    filter_keys = ['min_qual', 'max_repeat', 'max_missing', 'min_length', 'inner',
                   'include_missing', 'window', 'reverse']
    args_dict['filter_args'] = dict((k, args_dict[k]) for k in args_dict if k in filter_keys)
    for k in args_dict['filter_args']:  del args_dict[k]

    # Calls quality processing function
    del args_dict['seq_files']
    if 'out_files' in args_dict:  del args_dict['out_files']
    for i, f in enumerate(args.__dict__['seq_files']):
        args_dict['seq_file'] = f
        args_dict['out_file'] = args.__dict__['out_files'][i] \
            if args.__dict__['out_files'] else None
        filterSeq(**args_dict)
