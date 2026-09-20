#!/usr/bin/env python3
"""
Converts sequence headers to the pRESTO format
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from presto import __version__, __date__

# Imports
import os
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent
from time import time
from Bio import SeqIO

# Presto imports
from presto.Defaults import default_out_args
from presto.Annotation import flattenAnnotation, convertGenericHeader, convert454Header, \
                              convertGenbankHeader, convertIlluminaHeader, convertIMGTHeader, \
                              convertSRAHeader, convertMIGECHeader
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.IO import getFileType, readSeqFile, countSeqFile, getOutputHandle, \
                      openFile, printLog, printProgress


def convertHeaders(seq_file, convert_func, convert_args={}, out_file=None, out_args=default_out_args):
    """
    Converts sequence headers to the pRESTO format

    Arguments:
      seq_file : the sequence file name.
      convert_func : the function used to convert sequence headers.
      convert_args : a dictionary of arguments to pass to convert_func.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      str: the output sequence file name.
    """
    # Define subcommand label dictionary
    cmd_dict = {convertGenericHeader: 'generic',
                convert454Header: '454',
                convertGenbankHeader: 'genbank',
                convertIlluminaHeader: 'illumina',
                convertIMGTHeader: 'imgt',
                convertMIGECHeader: 'migec',
                convertSRAHeader: 'sra'}

    log = OrderedDict()
    log['START'] = 'ConvertHeaders'
    log['COMMAND'] = cmd_dict[convert_func]
    log['FILE'] = os.path.basename(seq_file)
    printLog(log)

    # Open input file
    in_type = getFileType(seq_file)
    seq_iter = readSeqFile(seq_file)
    if out_args['out_type'] is None:  out_args['out_type'] = in_type

    # Wrapper for opening handles and writers
    def _open(x, out_file=out_file):
        if out_file is not None and x == 'pass':
            # For explicit output files, check if gzip is needed
            if out_args.get('gzip_output', False) and not out_file.endswith('.gz'):
                out_file = out_file + '.gz'
            handle = openFile(out_file, 'w')
        else:
            handle = getOutputHandle(seq_file,
                                     'convert-%s' % x,
                                     out_dir=out_args['out_dir'],
                                     out_name=out_args['out_name'],
                                     out_type=out_args['out_type'],
                                     gzip_output=out_args.get('gzip_output', False))
        return handle

    # Count records
    result_count = countSeqFile(seq_file)

    # Set additional conversion arguments
    if convert_func in [convertGenericHeader, convertGenbankHeader]:
        convert_args.update({'delimiter': out_args['delimiter']})

    # Intialize file handles
    pass_handle, fail_handle = None, None

    # Iterate over sequences
    start_time = time()
    seq_count = pass_count = fail_count = 0
    for seq in seq_iter:
        # Print progress for previous iteration and update count
        printProgress(seq_count, result_count, 0.05, start_time=start_time)
        seq_count += 1

        # Convert header
        header = convert_func(seq.description, **convert_args)

        if header is not None:
            # Write successfully converted sequences
            pass_count += 1
            seq.id = seq.name = flattenAnnotation(header, out_args['delimiter'])
            seq.description = ''
            try:
                SeqIO.write(seq, pass_handle, out_args['out_type'])
            except AttributeError:
                # Open output file
                pass_handle = _open('pass')
                SeqIO.write(seq, pass_handle, out_args['out_type'])
        else:
            fail_count += 1
            if out_args['failed']:
                # Write unconverted sequences
                try:
                    SeqIO.write(seq, fail_handle, out_args['out_type'])
                except AttributeError:
                    # Open output file
                    fail_handle = _open('fail')
                    SeqIO.write(seq, fail_handle, out_args['out_type'])

    # Print counts
    printProgress(seq_count, result_count, 0.05, start_time=start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(pass_handle.name) if pass_handle is not None else None
    log['SEQUENCES'] = seq_count
    log['PASS'] = pass_count
    log['FAIL'] = fail_count
    log['END'] = 'ConvertHeaders'
    printLog(log)

    # Close file handles
    if pass_handle is not None:  pass_handle.close()
    if fail_handle is not None:  fail_handle.close()

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
                 convert-pass
                     reads passing header conversion.
                 convert-fail
                     raw reads failing header conversion.

             output annotation fields:
                 <format defined>
                     the annotation fields added are specific to the header format of the
                     input file.
             ''')

    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s %s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', metavar='',
                                       help='Conversion method')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Parent parser defining universal argument
    parent_parser = getCommonArgParser(log=False)

    # Subparser for generic header conversion
    parser_generic = subparsers.add_parser('generic', parents=[parent_parser],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='''Converts sequence headers without a known
                                            annotation system.''',
                                           description='''Converts sequence headers without a known
                                            annotation system.''')
    parser_generic.set_defaults(convert_func=convertGenericHeader)

    # Subparser for conversion of 454 headers
    parser_454 = subparsers.add_parser('454', parents=[parent_parser],
                                       formatter_class=CommonHelpFormatter, add_help=False,
                                       help='''Converts Roche 454 sequence headers.''',
                                       description='''Converts Roche 454 sequence headers.''')
    parser_454.set_defaults(convert_func=convert454Header)

    # Subparser for conversion of GenBank and RefSeq headers
    parser_genbank = subparsers.add_parser('genbank', parents=[parent_parser],
                                           formatter_class=CommonHelpFormatter, add_help=False,
                                           help='''Converts NCBI GenBank and RefSeq
                                                sequence headers.''',
                                           description='''Converts NCBI GenBank and RefSeq
                                                sequence headers.''')
    parser_genbank.set_defaults(convert_func=convertGenbankHeader)

    # Subparser for conversion of Illumina headers
    parser_illumina = subparsers.add_parser('illumina', parents=[parent_parser],
                                            formatter_class=CommonHelpFormatter, add_help=False,
                                            help='''Converts Illumina sequence headers.''',
                                            description='''Converts Illumina sequence headers.''')
    parser_illumina.set_defaults(convert_func=convertIlluminaHeader)

    # Subparser for conversion of IMGT germline headers
    parser_imgt = subparsers.add_parser('imgt', parents=[parent_parser],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='''Converts sequence headers output by
                                             IMGT/GENE-DB.''',
                                        description='''Converts sequence headers output by
                                             IMGT/GENE-DB.''')
    group_imgt = parser_imgt.add_argument_group('conversion arguments')
    group_imgt.add_argument('--simple', action='store_true', dest='simple',
                            help='''If specified, only the allele name, and no other
                                 annotations, will appear in the converted sequence
                                 header.''')
    parser_imgt.set_defaults(convert_func=convertIMGTHeader)

    # Subparser for conversion of MIGEC headers
    parser_migec = subparsers.add_parser('migec', parents=[parent_parser],
                                         formatter_class=CommonHelpFormatter, add_help=False,
                                         help='''Converts headers for consensus sequence generated
                                              by the MIGEC tool.''',
                                         description='''Converts headers for consensus sequence generated
                                              by the MIGEC tool.''')
    parser_migec.set_defaults(convert_func=convertMIGECHeader)

    # Subparser for conversion of SRA headers
    parser_sra = subparsers.add_parser('sra', parents=[parent_parser], add_help=False,
                                       formatter_class=CommonHelpFormatter,
                                       help='''Converts NCBI SRA or EMBL-EBI ENA sequence headers.''',
                                       description='''Converts NCBI SRA or EMBL-EBI ENA sequence headers.''')
    parser_sra.set_defaults(convert_func=convertSRAHeader)

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

    # Create convert_args
    convert_keys = ['simple']
    args_dict['convert_args'] = dict((k, args_dict[k]) for k in args_dict \
                                     if k in convert_keys)
    for k in args_dict['convert_args']:  del args_dict[k]

    # Calls header conversion function
    del args_dict['seq_files']
    if 'out_files' in args_dict:  del args_dict['out_files']
    for i, f in enumerate(args.__dict__['seq_files']):
        args_dict['seq_file'] = f
        args_dict['out_file'] = args.__dict__['out_files'][i] \
            if args.__dict__['out_files'] else None
        convertHeaders(**args_dict)
