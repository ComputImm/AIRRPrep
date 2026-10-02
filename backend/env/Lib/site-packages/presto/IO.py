"""
File I/O and logging functions
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from presto import __version__, __date__

# Imports
import gzip
import math
import re
import os
import sys
from collections import OrderedDict
from time import time, strftime
from Bio import SeqIO

# Presto imports
from presto.Defaults import default_delimiter, default_barcode_field
from presto.Annotation import parseAnnotation


def openFile(filename, mode='r'):
    """
    Opens a file with automatic gzip support
    
    Arguments:
      filename (str): path to the file
      mode (str): file opening mode
      
    Returns:
      file handle: opened file handle
    """
    if filename.endswith('.gz'):
        return gzip.open(filename, mode + 't')
    else:
        return open(filename, mode)


def readPrimerFile(primer_file, replace_special=True):
    """
    Processes primer sequences from file

    Arguments:
      primer_file (str): name of the FASTA file containing primer sequences.
      replace_special (bool): if True replace whitespace and pRESTO annotation
                              delimiters with an underscore.

    Returns:
      dict: Dictionary mapping primer ID to sequence.
    """
    if replace_special:  parse_id = lambda x: re.sub(r'[\s,=|]+', '_', x)
    else:  parse_id = lambda x: x

    with openFile(primer_file, 'r') as primer_handle:
        primer_iter = SeqIO.parse(primer_handle, 'fasta')
        primers = {parse_id(p.description): str(p.seq).upper() for p in primer_iter}

    return primers


def getFileType(filename):
    """
    Determines the type of a file by file extension

    Arguments:
      filename : Filename

    Returns:
      str : String defining the sequence type for SeqIO operations
    """
    # Read and check file
    try:
        # Handle .gz extensions
        if filename.endswith('.gz'):
            # Remove .gz and get the underlying file type
            filename_no_gz = filename[:-3]
            file_type = os.path.splitext(filename_no_gz)[1].lower().lstrip('.')
        else:
            file_type = os.path.splitext(filename)[1].lower().lstrip('.')
            
        if file_type in ('fasta', 'fna', 'fa'):  
            file_type = 'fasta'
        elif file_type in ('fastq', 'fq'):  
            file_type = 'fastq'
        elif file_type in ('tab', 'tsv'):  
            file_type = 'tab'
        else:
            # Handle unrecognized extensions - return as-is for now
            pass
            
    except IOError:
        printError('File %s cannot be read.' % filename)
    except Exception as e:
        printError('File %s is invalid with exception: %s.' % (filename, e))

    return file_type


# TODO:  Should probably be separate functions for index=True and index=False
def readSeqFile(seq_file, index=False, key_func=None):
    """
    Reads FASTA/FASTQ files

    Arguments:
      seq_file : FASTA or FASTQ file containing sample sequences
      index : If True return a dictionary from SeqIO.index();
              if False return an iterator from SeqIO.parse()
      key_func : the key_function argument to pass to SeqIO.index if
                 index=True

    Returns:
      iter : an interator of SeqRecords if index=False. A dict if True.
    """
    # Read and check file
    try:
        seq_type = getFileType(seq_file)
        if seq_type not in ('fasta', 'fastq'):
            printError('File %s has an unrecognized type.' % seq_file)

        if index:
            # For indexing, we need different approaches for gzip vs regular files
            if seq_file.endswith('.gz'):
                # For gzip files, we can't use SeqIO.index directly, so we'll read into memory.
                # SeqIO.index() cannot index regular .gz files, only BGZF format.
                with openFile(seq_file, 'r') as handle:
                    # Use key_func if possible for consistent behavior with non-.gz indexing
                    if key_func is None:
                        seq_records = {rec.id: rec for rec in SeqIO.parse(handle, seq_type)}
                    else:
                        seq_records = {key_func(rec.id): rec for rec in SeqIO.parse(handle, seq_type)}
            else:
                seq_records = SeqIO.index(seq_file, seq_type, key_function=key_func)
        else:
            # For non-index case, return iterator directly from SeqIO.parse
            if seq_file.endswith('.gz'):
                handle = openFile(seq_file, 'r')
                seq_records = SeqIO.parse(handle, seq_type)
            else:
                seq_records = SeqIO.parse(seq_file, seq_type)
    except IOError:
        printError('File %s cannot be read.' % seq_file)
    except Exception as e:
        printError('File %s is invalid with exception: %s.' % (seq_file, e))

    return seq_records


def readReferenceFile(ref_file):
    """
    Create a dictionary of cleaned and ungapped reference sequences.

    Arguments:
      ref_file : reference sequences in fasta format.

    Returns:
      dict : cleaned and ungapped reference sequences;
             with the key as the sequence ID and value as a Bio.SeqRecord for each reference sequence.
    """
    def _clean(rec):
        rec.seq = rec.seq.replace('-','').replace('.','').upper()
        rec.name = rec.description = ''
        return rec

    ref_dict = {s.id: _clean(s) for s in readSeqFile(ref_file)}

    return ref_dict


def countSeqFile(seq_file):
    """
    Counts the records in FASTA/FASTQ files

    Arguments:
      seq_file : FASTA or FASTQ file containing sample sequences

    Returns:
      int : Count of records in the sequence file
    """
    # Count records and check file
    try:
        seq_records = readSeqFile(seq_file, index=True)
        result_count = len(seq_records)
        # Close the indexed file if it's a SeqIO.index object
        if hasattr(seq_records, 'close'):
            seq_records.close()
    except IOError:
        printError('File %s cannot be read.' % seq_file)
    except Exception as e:
        printError('File %s is invalid with exception %s.' % (seq_file, e))
    else:
        if result_count == 0:  printError('File %s is empty.' % seq_file)

    return result_count


def countSeqSets(seq_file, field=default_barcode_field, delimiter=default_delimiter):
    """
    Identifies sets of sequences with the same ID field

    Arguments:
      seq_file : FASTA or FASTQ file containing sample sequences
      field : Annotation field containing set IDs
      delimiter : Tuple of delimiters for (fields, values, value lists)

    Returns:
      int : Count of unit set IDs in the sequence file
    """
    # Count records and check file
    try:
        id_set = set()
        for seq in readSeqFile(seq_file):
            id_set.add(parseAnnotation(seq.description, delimiter=delimiter)[field])
        result_count = len(id_set)
    except IOError:
        printError('File %s cannot be read.' % seq_file)
    except Exception as e:
        printError('File %s is invalid with exception %s.' % (seq_file, e))
    else:
        if result_count == 0:  printError('File %s is empty.' % seq_file)

    return result_count


def getOutputHandle(in_file, out_label=None, out_dir=None, out_name=None, out_type=None, gzip_output=False):
    """
    Opens an output file handle

    Arguments:
      in_file : Input filename
      out_label : Text to be inserted before the file extension;
                  if None do not add a label
      out_type : the file extension of the output file;
                 if None use input file extension
      out_dir : the output directory;
                if None use directory of input file
      out_name : the short filename to use for the output file;
                 if None use input file short name
      gzip_output : if True, create gzip compressed output

    Returns:
      file : File handle
    """
    # Get in_file components
    dir_name, file_name = os.path.split(in_file)
    
    # Handle input files that might be gzipped
    if file_name.endswith('.gz'):
        short_name, ext_name = os.path.splitext(file_name[:-3])  # Remove .gz first
        was_gzipped = True
    else:
        short_name, ext_name = os.path.splitext(file_name)
        was_gzipped = False

    # Define output directory
    if out_dir is None:
        out_dir = dir_name
    else:
        out_dir = os.path.abspath(out_dir)
        if not os.path.exists(out_dir):  os.mkdir(out_dir)
    
    # Define output file prefix
    if out_name is None:  out_name = short_name
    # Define output file extension - preserve original format if out_type is None
    if out_type is None:  
        out_type = ext_name.lstrip('.')
    else:
        # If out_type is specified, check if we should preserve original extension format
        original_ext = ext_name.lstrip('.')
        # Map standardized types back to original format when they match
        if out_type == 'fastq' and original_ext in ('fq', 'fastq'):
            out_type = original_ext
        elif out_type == 'fasta' and original_ext in ('fa', 'fasta'):
            out_type = original_ext

    # Define output file name
    if out_label is None:
        out_file = os.path.join(out_dir, '%s.%s' % (out_name, out_type))
    else:
        out_file = os.path.join(out_dir, '%s_%s.%s' % (out_name, out_label, out_type))
    
    # Add .gz extension if explicitly requested or if input was gzipped 
    # (preserve compression by default). When gzip_output=True, force 
    # compression; when False (default), auto-detect from input. Examples:
    # - .fasta.gz in will output .fasta.gz
    # - .fasta.gz in + --gzip-output will output .fasta.gz 
    # - .fasta in will output .fasta
    # - .fasta in + --gzip-output will output .fasta.gz
    if gzip_output is True or (gzip_output is False and was_gzipped):
        out_file += '.gz'

    # Open and return handle
    try:
        return openFile(out_file, 'w')
    except:
        printError('File %s cannot be opened.' % out_file)


def printLog(record, handle=sys.stdout, inset=None):
    """
    Formats a dictionary into a log string

    Arguments:
      record : a dict or OrderedDict of field names mapping to values.
      handle : the file handle to write the log to;
               if None do not write to file.
      inset : minimum field name inset;
              if None automatically space field names.

    Returns:
      str: Formatted multi-line string in the log format.
    """
    # Return empty string if empty dictionary passed
    if not record:
        return ''

    # Determine inset
    if inset is None:  inset = max(map(len, record))

    # Assemble log string
    record_str = ''
    if isinstance(record, OrderedDict):
        key_list = list(record.keys())
    else:
        key_list = sorted(record)
    for key in key_list:
        record_str += '%s%s> %s\n' % (' ' * (inset - len(key)), key, record[key])

    # Write log record
    if handle is not None:
        try:
            handle.write('%s\n' % record_str)
        except IOError as e:
            printWarning('I/O error writing to log file: %s' % e.strerror)

    return record_str


def printMessage(message, start_time=None, end=False, width=25):
    """
    Prints a progress message to standard out

    Arguments:
      message : Current task message
      start_time : task start time returned by time.time();
                   if None do not add run time to progress
      end : If True print final message (add newline)
      width : Maximum number of characters for messages
    """
    # Define progress bar
    bar = 'PROGRESS> %s |%s|' % (strftime('%H:%M:%S'), message.ljust(width))

    # Add run time to bar if start_time is specified
    if start_time is not None:
        bar = '%s %.1f min' % (bar, (time() - start_time)/60)

    # Print progress bar
    if end:
        print('\r%s\n' % bar)
        sys.stdout.flush()
    else:
        print('\r%s' % bar, end='')
        sys.stdout.flush()


def printCount(current, step, start_time=None, task=None, end=False):
    """
    Prints a progress bar to standard out

    Arguments:
      current (int): count of completed tasks.
      step (int): an int defining the progress increment to print at.
      start_time (time.time): task start time returned by time.time();
                              if None do not add run time to progress
      task (str): name of task to display.
      end (bool): if True print final log (add newline).
    """
    try:
        # Check update condition
        update = (current % step == 0)
    except:
        # Return on modulo by zero error
        return None
    else:
        # Check end condition and return if no update needed
        if not end and not update:
            return None

    # Define progress bar
    bar = '%s (%s)' % (strftime('%H:%M:%S'), current)

    # Add run time to bar if start_time is specified
    if start_time is not None:
        bar = '%s %.1f min' % (bar, (time() - start_time)/60)

    # Prefix with task
    if task is not None:
        bar = '[%s] %s' % (task, bar)

    # Print progress bar
    if current == 0:
        print('PROGRESS> %s' % bar, end='')
        sys.stdout.flush()
    elif end:
        print('\rPROGRESS> %s\n' % bar)
        sys.stdout.flush()
    else:
        print('\rPROGRESS> %s' % bar, end='')
        sys.stdout.flush()


def printProgress(current, total, step, start_time=None, task=None, end=False):
    """
    Prints a progress bar to standard out

    Arguments:
      current (int): count of completed tasks.
      total (int): total task count.
      step (float): float defining the fractional progress increment to print at.
      start_time (float): task start time returned by time.time();
                          if None do not add run time to progress
      task (str): name of task to display.
      end (bool): if True print final log (add newline).
    """
    try:
        # Check update condition
        update = (current % math.ceil(step*total) == 0)
    except:
        # Return on modulo by zero error
        return None
    else:
        # Check end condition and return if no update needed
        if current == total:
            end = True
        if not end and not update:
            return None

    # Define progress bar
    p = float(current) / total
    c = format(current, '%i,d' % len(format(total, ',d')))
    bar = '%s |%-20s| %3.0f%% (%s)' % (strftime('%H:%M:%S'), '#' * int(p*20), p*100, c)

    # Add run time to bar if start_time is specified
    if start_time is not None:
        bar = '%s %.1f min' % (bar, (time() - start_time)/60)

    # Prefix with task
    if task is not None:
        bar = '[%s] %s' % (task, bar)

    # Print progress bar
    if current == 0:
        print('PROGRESS> %s' % bar, end='')
        sys.stdout.flush()
    elif end:
        print('\rPROGRESS> %s\n' % bar)
        sys.stdout.flush()
    else:
        print('\rPROGRESS> %s' % bar, end='')
        sys.stdout.flush()


def printWarning(message, newline=False):
    """
    Prints a warning to standard error

    Arguments:
      message (str): warning message.
      newline (bool): prefix with a newline if True.
    """
    prefix = '\n' if newline else ''
    sys.stderr.write('%sWARNING> %s\n' % (prefix, message))


def printError(message, exit=True, newline=False):
    """
    Prints an error to standard error and exits

    Arguments:
      message (str): error message.
      exit (bool): if True exit after the message.
      newline (bool): prefix with a newline if True.
    """
    prefix = '\n' if newline else ''
    if exit:
        sys.exit('%sERROR> %s\n' % (prefix, message))
    else:
        sys.stderr.write('%sERROR> %s\n' % (prefix, message))


def printDebug(message, debug=True, newline=False):
    """
    Prints a debug message to standard error

    Arguments:
      message (str): message.
      debug (bool): if True print the message.
      newline (bool): prefix with a newline if True.
    """
    if debug:
        prefix = '\n' if newline else ''
        sys.stderr.write('%sDEBUG> %s\n' % (prefix, message))
