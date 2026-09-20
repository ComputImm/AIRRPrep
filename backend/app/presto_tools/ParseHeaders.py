#!C:\Users\sahar\OneDrive\Desktop\shayesteh\presto-backend\venv\Scripts\python.exe
"""
Parses pRESTO annotations in FASTA/FASTQ sequence headers
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from presto import __version__, __date__

# Imports
import csv
import os
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent
from time import time
from Bio import SeqIO

# Presto imports
from presto.Defaults import default_separator, default_out_args
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.Annotation import parseAnnotation, flattenAnnotation, \
                              addHeader, collapseHeader, copyHeader, deleteHeader, \
                              expandHeader, mergeHeader, renameHeader
from presto.IO import getFileType, readSeqFile, countSeqFile, getOutputHandle, \
                      openFile, printLog, printProgress


def modifyHeaders(seq_file, modify_func, modify_args, out_file=None, out_args=default_out_args):
    """
    Modifies sequence headers

    Arguments:
      seq_file : the sequence file name.
      modify_func : the function defining the modification operation.
      modify_args : a dictionary of arguments to pass to modify_func.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      str: output file name.
    """
    # Define subcommand label dictionary
    cmd_dict = {addHeader: 'add',
                copyHeader: 'copy',
                collapseHeader: 'collapse',
                deleteHeader: 'delete',
                expandHeader: 'expand',
                renameHeader: 'rename'}

    # Print parameter info
    log = OrderedDict()
    log['START'] = 'ParseHeaders'
    log['COMMAND'] = cmd_dict.get(modify_func, modify_func.__name__)
    log['FILE'] = os.path.basename(seq_file)
    for k in sorted(modify_args):
        v = modify_args[k]
        log[k.upper()] = ','.join(v) if isinstance(v, list) else v
    printLog(log)

    # Open file handles
    in_type = getFileType(seq_file)
    seq_iter = readSeqFile(seq_file)
    if out_args['out_type'] is None:  out_args['out_type'] = in_type
    if out_file is not None:
        # For explicit output files, check if gzip is needed
        if out_args.get('gzip_output', False) and not out_file.endswith('.gz'):
            out_file = out_file + '.gz'
        out_handle = openFile(out_file, 'w')
    else:
        out_handle = getOutputHandle(seq_file,
                                     'reheader',
                                     out_dir=out_args['out_dir'],
                                     out_name=out_args['out_name'],
                                     out_type=out_args['out_type'],
                                     gzip_output=out_args.get('gzip_output', False))
    # Count records
    result_count = countSeqFile(seq_file)

    # Iterate over sequences
    start_time = time()
    seq_count = 0
    for seq in seq_iter:
        # Print progress for previous iteration
        printProgress(seq_count, result_count, 0.05, start_time=start_time)

        #Update counts
        seq_count += 1

        # Modify header
        header = parseAnnotation(seq.description, delimiter=out_args['delimiter'])
        header = modify_func(header, delimiter=out_args['delimiter'], **modify_args)

        # Write new sequence
        seq.id = seq.name = flattenAnnotation(header, delimiter=out_args['delimiter'])
        seq.description = ''
        SeqIO.write(seq, out_handle, out_args['out_type'])

    # print counts
    printProgress(seq_count, result_count, 0.05, start_time=start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(out_handle.name)
    log['SEQUENCES'] = seq_count
    log['END'] = 'ParseHeaders'
    printLog(log)

    # Close file handles
    out_handle.close()

    return out_handle.name


def tableHeaders(seq_file, fields, out_file=None, out_args=default_out_args):
    """
    Builds a table of sequence header annotations

    Arguments:
      seq_file : the sequence file name.
      fields : the list of fields to output.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      str: output table file name
    """
    log = OrderedDict()
    log['START'] = 'ParseHeaders'
    log['COMMAND'] = 'table'
    log['FILE'] = os.path.basename(seq_file)
    printLog(log)

    # Open file handles
    seq_iter = readSeqFile(seq_file)
    if out_file is not None:
        # For explicit output files, check if gzip is needed
        if out_args.get('gzip_output', False) and not out_file.endswith('.gz'):
            out_file = out_file + '.gz'
        out_handle = openFile(out_file, 'w')
    else:
        out_handle = getOutputHandle(seq_file,
                                     'headers',
                                     out_dir=out_args['out_dir'],
                                     out_name=out_args['out_name'],
                                     out_type='tab',
                                     gzip_output=out_args.get('gzip_output', False))
    # Count records
    result_count = countSeqFile(seq_file)

    # Open csv writer and write header
    out_writer = csv.DictWriter(out_handle, extrasaction='ignore', restval='',
                                delimiter='\t', fieldnames=fields)
    out_writer.writeheader()

    # Iterate over sequences
    start_time = time()
    seq_count = pass_count = fail_count = 0
    for seq in seq_iter:
        # Print progress for previous iteration
        printProgress(seq_count, result_count, 0.05, start_time=start_time)

        # Get annotations
        seq_count += 1
        ann = parseAnnotation(seq.description, fields, delimiter=out_args['delimiter'])

        # Write records
        if ann:
            pass_count += 1
            out_writer.writerow(ann)
        else:
            fail_count += 1

    # Print counts
    printProgress(seq_count, result_count, 0.05, start_time=start_time)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(out_handle.name)
    log['SEQUENCES'] = seq_count
    log['PASS'] = pass_count
    log['FAIL'] = fail_count
    log['END'] = 'ParseHeaders'
    printLog(log)

    # Close file handles
    out_handle.close()

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
                 reheader-pass
                     reads passing annotation operation and modified accordingly.
                 reheader-fail
                     raw reads failing annotation operation.
                 headers
                     tab delimited table of the selected annotations.

             output annotation fields:
                 <user defined>
                     annotation fields specified by the -f argument.
             ''')

    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            formatter_class=CommonHelpFormatter, add_help=False)
    group_help = parser.add_argument_group('help')
    group_help.add_argument('--version', action='version',
                            version='%(prog)s:' + ' %s %s' %(__version__, __date__))
    group_help.add_argument('-h', '--help', action='help', help='show this help message and exit')
    subparsers = parser.add_subparsers(title='subcommands', dest='command', metavar='',
                                       help='Annotation operation')
    # TODO:  This is a temporary fix for Python issue 9253
    subparsers.required = True

    # Subparser to add header fields
    parser_add = subparsers.add_parser('add', parents=[getCommonArgParser(log=False)],
                                       formatter_class=CommonHelpFormatter, add_help=False,
                                       help='Adds field/value pairs to header annotations',
                                       description='Adds field/value pairs to header annotations')
    group_add = parser_add.add_argument_group('parsing arguments')
    group_add.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                           help='List of fields to add.')
    group_add.add_argument('-u', nargs='+', action='store', dest='values', required=True,
                           help='List of values to add for each field.')
    parser_add.set_defaults(func=modifyHeaders)
    parser_add.set_defaults(modify_func=addHeader)

    # Subparser to collapse header fields
    parser_collapse = subparsers.add_parser('collapse', parents=[getCommonArgParser(log=False)],
                                            formatter_class=CommonHelpFormatter, add_help=False,
                                            help='Collapses header annotations with multiple entries',
                                            description='Collapses header annotations with multiple entries')
    group_collapse = parser_collapse.add_argument_group('parsing arguments')
    group_collapse.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                                help='List of fields to collapse.')
    group_collapse.add_argument('--act', nargs='+', action='store', dest='actions', required=True,
                                choices=['min', 'max', 'sum', 'first', 'last', 'set', 'cat'],
                                help='''List of actions to take for each field defining how
                                     each annotation will be combined into a single value.
                                     The actions "min", "max", "sum" perform the corresponding
                                     mathematical operation on numeric annotations. The
                                     actions "first" and "last" choose the value from the
                                     corresponding position in the annotation. The action
                                     "set" collapses annotations into a comma delimited
                                     list of unique values. The action "cat" concatenates
                                     the values together into a single string.''')
    parser_collapse.set_defaults(func=modifyHeaders)
    parser_collapse.set_defaults(modify_func=collapseHeader)

    # Subparser to copy header fields
    parser_copy = subparsers.add_parser('copy', parents=[getCommonArgParser(log=False)],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Copies header annotation fields',
                                        description='Copies header annotation fields')
    group_copy = parser_copy.add_argument_group('parsing arguments')
    group_copy.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                            help='List of fields to copy.')
    group_copy.add_argument('-k', nargs='+', action='store', dest='names', required=True,
                            help='''List of names for each copied field. If the new field
                                 is already present, the copied field will be merged into
                                 the existing field.''')
    group_copy.add_argument('--act', nargs='+', action='store', dest='actions', required=False,
                            choices=['min', 'max', 'sum', 'first', 'last', 'set', 'cat'],
                            help='''List of collapse actions to take on each new field
                                 following the copy operation defining how each annotation
                                 will be combined into a single value. The actions
                                 "min", "max", "sum" perform the corresponding
                                 mathematical operation on numeric annotations. The
                                 actions "first" and "last" choose the value from the
                                 corresponding position in the annotation. The action
                                 "set" collapses annotations into a comma delimited
                                 list of unique values. The action "cat" concatenates
                                 the values together into a single string.''')
    parser_copy.set_defaults(func=modifyHeaders)
    parser_copy.set_defaults(modify_func=copyHeader)

    # Subparser to delete header fields
    parser_delete = subparsers.add_parser('delete', parents=[getCommonArgParser(log=False)],
                                          formatter_class=CommonHelpFormatter, add_help=False,
                                          help='Deletes fields from header annotations',
                                          description='Deletes fields from header annotations')
    group_delete = parser_delete.add_argument_group('parsing arguments')
    group_delete.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                              help='List of fields to delete.')
    parser_delete.set_defaults(func=modifyHeaders)
    parser_delete.set_defaults(modify_func=deleteHeader)

    # Subparser to expand header fields
    parser_expand = subparsers.add_parser('expand', parents=[getCommonArgParser(log=False)],
                                          formatter_class=CommonHelpFormatter, add_help=False,
                                          help='Expands annotation fields with multiple values',
                                          description='Expands annotation fields with multiple values')
    group_expand = parser_expand.add_argument_group('parsing arguments')
    group_expand.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                              help='List of fields to expand.')
    group_expand.add_argument('--sep', action='store', dest='separator',
                              default=default_separator,
                              help='The character separating each value in the fields.')
    parser_expand.set_defaults(func=modifyHeaders)
    parser_expand.set_defaults(modify_func=expandHeader)

    # Subparser to merge header fields
    parser_merge = subparsers.add_parser('merge', parents=[getCommonArgParser(log=False)],
                                        formatter_class=CommonHelpFormatter, add_help=False,
                                        help='Merge multiple annotations fields into a single field',
                                        description='Merge multiple annotations fields into a single field')
    group_merge = parser_merge.add_argument_group('parsing arguments')
    group_merge.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                             help='List of fields to merge.')
    group_merge.add_argument('-k', action='store', dest='name', required=True,
                             help='''Name for the merged field. If the new field
                                  is already present, the merged fields will be merged into
                                  the existing field.''')
    group_merge.add_argument('--act', action='store', dest='action', required=False,
                             choices=['min', 'max', 'sum', 'set', 'cat'],
                             help='''List of collapse actions to take on the new field
                                  following the merge defining how to combine the annotations
                                  into a single value. The actions "min", "max", "sum" perform
                                  the corresponding mathematical operation on numeric annotations.
                                  The action "set" collapses annotations into a comma delimited
                                  list of unique values. The action "cat" concatenates
                                  the values together into a single string.''')
    group_merge.add_argument('--delete', action='store_true', dest='delete',
                             help='''If specified, delete the field that were merged from the
                                  output header.''')
    parser_merge.set_defaults(func=modifyHeaders)
    parser_merge.set_defaults(modify_func=mergeHeader)

    # Subparser to rename header fields
    parser_rename = subparsers.add_parser('rename', parents=[getCommonArgParser(log=False)],
                                          formatter_class=CommonHelpFormatter, add_help=False,
                                          help='Renames header annotation fields',
                                          description='Renames header annotation fields')
    group_rename = parser_rename.add_argument_group('parsing arguments')
    group_rename.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                              help='List of fields to rename.')
    group_rename.add_argument('-k', nargs='+', action='store', dest='names', required=True,
                              help='''List of new names for each field. If the new field is
                                   already present, the renamed field will be merged into
                                   the existing field and the old field will be deleted.''')
    group_rename.add_argument('--act', nargs='+', action='store', dest='actions', required=False,
                              choices=['min', 'max', 'sum', 'first', 'last', 'set', 'cat'],
                              help='''List of collapse actions to take on each new field
                                   following the rename operation defining how each annotation
                                   will be combined into a single value. The actions
                                   "min", "max", "sum" perform the corresponding
                                   mathematical operation on numeric annotations. The
                                   actions "first" and "last" choose the value from the
                                   corresponding position in the annotation. The action
                                   "set" collapses annotations into a comma delimited
                                   list of unique values. The action "cat" concatenates
                                   the values together into a single string.''')
    parser_rename.set_defaults(func=modifyHeaders)
    parser_rename.set_defaults(modify_func=renameHeader)

    # Subparser to create a header table
    parser_table = subparsers.add_parser('table', parents=[getCommonArgParser(seq_out=False, log=False)],
                                         formatter_class=CommonHelpFormatter, add_help=False,
                                         help='Writes sequence headers to a table',
                                         description='Writes sequence headers to a table')
    group_table = parser_table.add_argument_group('parsing arguments')
    group_table.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                             help='''List of fields to collect. The sequence identifier may
                                  be specified using the hidden field name "ID".''')
    parser_table.set_defaults(func=tableHeaders)

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
    if 'fields' in args_dict and args_dict['fields']:
        args_dict['fields'] = list(map(str.upper, args_dict['fields']))

    # Built modify_args dictionary
    if args.func == modifyHeaders:
        modify_args = {}
        if 'field' in args_dict:
            modify_args['field'] = args_dict.pop('field')
        if 'fields' in args_dict:
            modify_args['fields'] = args_dict.pop('fields')
        if 'action' in args_dict:
            modify_args['action'] = args_dict.pop('action') if args_dict['action'] is None \
                                    else str.lower(args_dict.pop('action'))
        if 'actions' in args_dict:
            modify_args['actions'] = args_dict.pop('actions') if args_dict['actions'] is None \
                                     else list(map(str.lower, args_dict.pop('actions')))
        if 'name' in args_dict:
            modify_args['name'] = str.upper(args_dict.pop('name'))
        if 'names' in args_dict:
            modify_args['names'] = list(map(str.upper, args_dict.pop('names')))
        if 'values' in args_dict:
            modify_args['values'] = args_dict.pop('values')
        if 'separator' in args_dict:
            modify_args['separator'] = args_dict.pop('separator')
        if 'delete' in args_dict:
                modify_args['delete'] = args_dict.pop('delete')
        args_dict['modify_args'] = modify_args

    # Check modify_args arguments
    if args.command == 'add' and len(modify_args['fields']) != len(modify_args['values']):
        parser.error('You must specify exactly one value (-u) per field (-f)')
    if args.command == 'collapse' and len(modify_args['fields']) != len(modify_args['actions']):
        parser.error('You must specify exactly one action (-a) per field (-f)')
    if args.command in ('copy', 'rename'):
        if len(modify_args['fields']) != len(modify_args['names']):
            parser.error('You must specify exactly one new name (-k) per field (-f)')
        if modify_args['actions'] is not None and len(modify_args['actions']) != len(modify_args['names']):
            parser.error('You must specify exactly one action (--act) per new name (-k)')

    # Calls header processing function
    del args_dict['command']
    del args_dict['func']
    del args_dict['seq_files']
    if 'out_files' in args_dict:  del args_dict['out_files']
    for i, f in enumerate(args.__dict__['seq_files']):
        args_dict['seq_file'] = f
        args_dict['out_file'] = args.__dict__['out_files'][i] \
            if args.__dict__['out_files'] else None
        args.func(**args_dict)
