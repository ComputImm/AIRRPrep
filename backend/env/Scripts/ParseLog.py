#!E:\AIRR-Preprocessing\Preprocessing-code\git\backend\env\Scripts\python.exe
"""
Parses records in the console log of pRESTO modules
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'

# Imports
import csv
import os
from argparse import ArgumentParser
from collections import OrderedDict
from textwrap import dedent
from time import time

# Presto imports
from presto.Defaults import default_out_args
from presto.Annotation import parseLog
from presto.Commandline import CommonHelpFormatter, checkArgs, getCommonArgParser, parseCommonArgs
from presto.IO import getOutputHandle, openFile, printLog, printCount


def tableLog(record_file, fields, out_file=None, out_args=default_out_args):
    """
    Converts a pRESTO log to a table of annotations

    Arguments:
      record_file : the log file name.
      fields : the list of fields to output.
      out_file : output file name. Automatically generated from the input file if None.
      out_args : common output argument dictionary from parseCommonArgs.

    Returns:
      str: the output table file name
    """
    log = OrderedDict()
    log['START'] = 'ParseLog'
    log['FILE'] = os.path.basename(record_file)
    printLog(log)

    # Open file handles
    log_handle = open(record_file)
    if out_file is not None:
        # For explicit output files, check if gzip is needed
        if out_args.get('gzip_output', False) and not out_file.endswith('.gz'):
            out_file = out_file + '.gz'
        out_handle = openFile(out_file, 'w')
    else:
        out_handle = getOutputHandle(record_file,
                                     'table',
                                      out_dir=out_args['out_dir'],
                                      out_name=out_args['out_name'],
                                      out_type='tab',
                                      gzip_output=out_args.get('gzip_output', False))

    # Open csv writer and write header
    out_writer = csv.DictWriter(out_handle, extrasaction='ignore', restval='',
                                delimiter='\t', fieldnames=fields)
    out_writer.writeheader()

    # Iterate over log records
    start_time = time()
    record = ''
    rec_count = pass_count = fail_count = 0
    for line in log_handle:
        if line.strip() == '' and record:
            # Print progress for previous iteration
            printCount(rec_count, 1e5, start_time=start_time)

            # Parse record block
            rec_count += 1
            record_dict = parseLog(record)

            # Write records
            if any([f in fields for f in record_dict]):
                pass_count += 1
                out_writer.writerow(record_dict)
            elif record_dict:
                fail_count += 1

            # Empty record string
            record = ''
        else:
            # Append to record
            record += line
    else:
        # Write final record
        if record:
            record_dict = parseLog(record)
            if any([f in fields for f in record_dict]):
                pass_count += 1
                out_writer.writerow(record_dict)
            elif record_dict:
                fail_count += 1

    # Print counts
    printCount(rec_count, 1e5, start_time, end=True)
    log = OrderedDict()
    log['OUTPUT'] = os.path.basename(out_handle.name)
    log['RECORDS'] = rec_count
    log['PASS'] = pass_count
    log['FAIL'] = fail_count
    log['END'] = 'ParseLog'
    printLog(log)

    # Close file handles
    log_handle.close()
    out_handle.close()

    return log_handle.name


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
                 table
                     tab delimited table of the selected annotations.

             output annotation fields:
                 <user defined>
                     annotation fields specified by the -f argument.
             ''')

    # Define ArgumentParser
    parser = ArgumentParser(description=__doc__, epilog=fields,
                            parents=[getCommonArgParser(seq_in=False, seq_out=False,
                                                        failed=False, log=False)],
                            formatter_class=CommonHelpFormatter, add_help=False)

    group_log = parser.add_argument_group('parsing arguments')
    group_log.add_argument('-l', nargs='+', action='store', dest='record_files', required=True,
                           help='List of log files to parse.')
    group_log.add_argument('-f', nargs='+', action='store', dest='fields', required=True,
                           help='''List of fields to collect. The sequence identifier may
                                be specified using the hidden field name "ID".''')

    return parser


if __name__ == '__main__':
    """
    Parses command line arguments and calls main function
    """
    # Parse arguments
    parser = getArgParser()
    args = parser.parse_args()
    checkArgs(parser)
    args_dict = parseCommonArgs(args, in_arg='record_files')
    # Convert case of fields
    if args_dict['fields']:  args_dict['fields'] = list(map(str.upper, args_dict['fields']))

    # Call parseLog for each log file
    del args_dict['record_files']
    if 'out_files' in args_dict:  del args_dict['out_files']
    for i, f in enumerate(args.__dict__['record_files']):
        args_dict['record_file'] = f
        args_dict['out_file'] = args.__dict__['out_files'][i] \
            if args.__dict__['out_files'] else None
        tableLog(**args_dict)
