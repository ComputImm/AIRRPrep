#!/usr/bin/env python3
"""
Unifies annotation fields based on grouping scheme
"""
# Info
__author__ = 'Ruoyi Jiang, Jason Vander Heiden'
from presto import __version__, __date__

# Imports
import os
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent

# Presto imports
from presto.Defaults import default_barcode_field, default_out_args
from presto.Commandline import checkArgs, CommonHelpFormatter, getCommonArgParser, parseCommonArgs
from presto.IO import printLog
from presto.Sequence import indexSeqSets, consensusUnify, deletionUnify
from presto.Multiprocessing import manageProcesses, collectSeqQueue, feedSeqQueue, \
                                   processSeqQueue

# Defaults
default_unify_field = 'SAMPLE'


def unifyHeaders(seq_file, collapse_func, set_field=default_barcode_field,
                 unify_field=default_unify_field, out_file=None, out_args=default_out_args,
                 nproc=None, queue_size=None):
    """
    Merges and filters annotation fields within groups

    Arguments:
      seq_file : the sample sequence file name.
      collapse_func : the function to use for collapsing annotations.
      set_field : the annotation containing set IDs.
      unify_field : the field for collection criteria.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.
      nproc : the number of processQueue processes;
              if None defaults to the number of CPUs.
      queue_size : maximum size of the argument queue;
                   if None defaults to 2*nproc.

    Returns:
      str: output file name.
    """
    # Print parameter info
    log = OrderedDict()
    log['START'] = 'UnifyHeaders'
    log['FILE'] = os.path.basename(seq_file)
    log['SET_FIELD'] = set_field
    log['UNIFY_FIELD'] = unify_field
    log['NPROC'] = nproc
    printLog(log)

    # Define feeder function and arguments
    index_args = {'field': set_field,
                  'delimiter': out_args['delimiter']}
    feed_func = feedSeqQueue
    feed_args = {'seq_file': seq_file,
                 'index_func': indexSeqSets,
                 'index_args': index_args}
    # Define worker function and arguments
    collapse_args = {'field': unify_field,
                     'delimiter': out_args['delimiter']}
    work_func = processSeqQueue
    work_args = {'process_func': collapse_func,
                 'process_args': collapse_args}
    # Define collector function and arguments
    collect_func = collectSeqQueue
    collect_args = {'seq_file': seq_file,
                    'label': 'unify',
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
    log['END'] = 'UnifyHeaders'
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
                 unify-pass
                    Reads passing annotation filtering or consensus.
                 unify-fail
                    Reading failing filtering.
             output annotation fields:
                 <user defined>
                     annotation fields specified by the -f and -k arguments.
             ''')
    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s %s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', metavar='',
                                       help='Annotation operation')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Parent parser
    parser_parent = getCommonArgParser(annotation=True, log=True, multiproc=True, seq_out=True)
    group_parent = parser_parent.add_argument_group('annotation arguments')
    group_parent.add_argument('-f', action='store', dest='set_field', type=str,
                             default=default_barcode_field,
                             help='''The annotation field containing annotations, such as the UMI
                                  barcode, for sequence grouping.''')
    group_parent.add_argument('-k', action='store', dest='unify_field', type=str,
                             default=default_unify_field,
                             help='''The name of the annotation field to find a consensus for
                                  per each sequence group.''')
    # Consensus arguments
    parser_cons = subparsers.add_parser('consensus', parents=[parser_parent],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Reassign fields to consensus values.',
                                        description='Reassign fields to consensus values.')
    parser_cons.set_defaults(collapse_func=consensusUnify)

    # Deletion arguments
    parser_del = subparsers.add_parser('delete', parents=[parser_parent],
                                       formatter_class=CommonHelpFormatter, add_help=False,
                                       help='Delete sequences with differing field values.',
                                       description='Delete sequences with differing field values.')
    parser_del.set_defaults(collapse_func=deletionUnify)

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
    if 'unify_field' in args_dict and args_dict['unify_field'] is not None:
        args_dict['unify_field'] = args_dict['unify_field'].upper()

    # Call cluster for each input file
    del args_dict['seq_files']
    if 'out_files' in args_dict:  del args_dict['out_files']
    for i, f in enumerate(args.__dict__['seq_files']):
        args_dict['seq_file'] = f
        args_dict['out_file'] = args.__dict__['out_files'][i] \
            if args.__dict__['out_files'] else None
        unifyHeaders(**args_dict)
