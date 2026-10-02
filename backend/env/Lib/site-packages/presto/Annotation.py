"""
Annotation functions
"""
# Info
__author__ = 'Jason Anthony Vander Heiden'
from presto import __version__, __date__

# Imports
import re
from collections import OrderedDict
from presto.Defaults import default_coord, default_delimiter, default_separator


def getCoordKey(header, coord_type=default_coord, delimiter=default_delimiter):
    """
    Return the coordinate identifier for a sequence description

    Arguments:
      header (str): Sequence header string
      coord_type (str): Sequence header format;
                   one of 'illumina', 'solexa', 'sra', 'ena', '454', or 'presto';
                   if unrecognized type or None, then return the input header.
      delimiter (tuple): Tuple of delimiters for (fields, values, value lists)

    Returns:
      str: Coordinate identifier as a string.
    """
    if coord_type in ('illumina', 'solexa'):
        return header.split()[0].split('/')[0].split('#')[0]
    elif coord_type in ('sra', 'ena'):
        return '.'.join(header.split()[0].split('.')[:2])
    elif coord_type == '454':
        return header.split()[0]
    elif coord_type == 'presto':
        return parseAnnotation(header, delimiter=delimiter)['ID']
    else:
        return header


def parseLog(record):
    """
    Parses an pRESTO log record

    Arguments:
      record (str): a string of lines representing a log record including newline characters.

    Returns:
      collections.OrderedDict: parsed log contain field and values pairs as a dictionary.
    """
    record_dict = OrderedDict()
    for line in record.split('\n'):
        line = line.strip().split('> ')
        if len(line) == 2:
            record_dict[line[0]] = line[1]

    return record_dict


def parseAnnotation(record, fields=None, delimiter=default_delimiter):
    """
    Extracts annotations from a FASTA/FASTQ sequence description

    Arguments:
      record : Description string to extract annotations from
      fields : List of fields to subset the return dictionary to;
               if None return all fields
      delimiter : a tuple of delimiters for (fields, values, value lists)

    Returns:
      OrderedDict : An OrderedDict of field/value pairs
    """
    annotation = record.split(delimiter[0])
    field_dict = OrderedDict([('ID', annotation.pop(0))])
    for ann in annotation:
        vals = ann.split(delimiter[1])
        field_dict[vals[0].upper()] = vals[1]

    # Subset return dictionary to requested fields
    if fields is not None:
        if not isinstance(fields, list):  fields = [fields]
        for f in set(field_dict).difference(fields):  del field_dict[f]

    return field_dict


def flattenAnnotation(ann_dict, delimiter=default_delimiter):
    """
    Converts annotations from a dictionary to a FASTA/FASTQ sequence description

    Arguments:
      ann_dict : Dictionary of field/value pairs
      delimiter : Tuple of delimiters for (fields, values, value lists)

    Returns:
      str : Formatted sequence description string
    """
    annotation = ann_dict.get('ID', 'NONE')
    for k, v in ann_dict.items():
        # Skip ID field
        if k.upper() == 'ID':
            continue

        if isinstance(v, list):
            v = delimiter[2].join([str(x) for x in v])
        annotation += '%s%s%s%s' % (delimiter[0], k.upper(), delimiter[1], v)

    return annotation


def mergeAnnotation(ann_dict_1, ann_dict_2, prepend=False,
                    delimiter=default_delimiter):
    """
    Merges non-ID field annotations from one field dictionary into another

    Arguments:
      ann_dict_1 : Dictionary of field/value pairs to append to
      ann_dict_2 : Dictionary of field/value pairs to merge with ann_dict_2
      prepend : If True then add ann_dict_2 values to the front of any ann_dict_1
                values that are already present, rather than the default behavior
                of appending ann_dict_2 values.
      delimiter : Tuple of delimiters for (fields, values, value lists)

    Returns:
      OrderedDict : Modified ann_dict_1 dictonary of field/value pairs
    """
    # Define merge order
    if prepend:
        def _merge(x, y):  return '%s%s%s' % (y, delimiter[2], x)
    else:
        def _merge(x, y):  return '%s%s%s' % (x, delimiter[2], y)

    merged_dict = ann_dict_1.copy()
    for k, v in ann_dict_2.items():
        # Skip ID field
        if k.upper() == 'ID':
            continue

        if k in merged_dict:
            if isinstance(merged_dict[k], list):
                merged_dict[k] = delimiter[2].join([str(x) for x in merged_dict[k]])
            if isinstance(v, list):
                v = delimiter[2].join([str(x) for x in v])
            merged_dict[k] = _merge(merged_dict[k], v)
        else:
            merged_dict[k.upper()] = v

    return merged_dict


def renameAnnotation(ann_dict, old_field, new_field, delimiter=default_delimiter):
    """
    Renames an annotation and merges annotations if the new name already exists

    Arguments:
      ann_dict : Dictionary of field/value pairs
      old_field : Old field name
      new_field : New field name
      delimiter : Tuple of delimiters for (fields, values, value lists)

    Returns:
      OrderedDict : Modified fields dictonary
    """
    if new_field in ann_dict:
        rename_dict = ann_dict.copy()
        del rename_dict[old_field]
        rename_dict = mergeAnnotation(rename_dict, {new_field:ann_dict[old_field]},
                                      delimiter=delimiter)
    else:
        rename_dict = OrderedDict([(new_field, v) if k == old_field else (k, v) \
                                   for k, v in ann_dict.items()])

    return rename_dict


# TODO:  this converted min/max/sum collapse to strings instead of floats (for rounding purposes). which is odd.
def collapseAnnotation(ann_dict, action, fields=None, delimiter=default_delimiter):
    """
    Collapses multiple annotations into new single annotations for each field

    Arguments:
      ann_dict : dictionary of field/value pairs
      action : collapse action to take;
               one of {min, max, sum, first, last, set, cat}
      fields : subset of ann_dict to _collapse;
               if None, collapse all but the ID field
      delimiter : Tuple of delimiters for (fields, values, value lists)

    Returns:
      OrderedDict : Modified field dictionary
    """
    # Define _collapse action
    if action == 'set':
        def _collapse(value):  return sorted(set(value))
    elif action == 'first':
        def _collapse(value):  return value[0]
    elif action == 'last':
        def _collapse(value):  return value[-1]
    elif action == 'min':
        def _collapse(value):  return '%.12g' % min([float(x or 0) for x in value])
    elif action == 'max':
        def _collapse(value):  return '%.12g' % max([float(x or 0) for x in value])
    elif action == 'sum':
        def _collapse(value):  return '%.12g' % sum([float(x or 0) for x in value])
    elif action == 'cat':
        def _collapse(value):  return ''.join([str(x) for x in value])
    else:
        def _collapse(value):  return value

    # Collapse fields
    collapse_dict = ann_dict.copy()
    for k, v in collapse_dict.items():
        if k.upper() == 'ID':
            continue
        if fields is None or k in fields:
            # Convert field to list
            if not isinstance(v, list) and isinstance(v, str):
                v = v.split(delimiter[2])
            elif not isinstance(v, list):
                v = [v]
            # Perform _collapse and reassign field
            collapse_dict[k] = _collapse(v)

    return collapse_dict


def getAnnotationValues(seq_iter, field, unique=False, delimiter=default_delimiter):
    """
    Gets the set of unique annotation values in a sequence set

    Arguments:
      seq_iter : Iterator or list of SeqRecord objects
      field : Annotation field to retrieve values for
      unique : If True return a list of only the unique values;
               if False return a list of all values
      delimiter : Tuple of delimiters for (fields, values, value lists)

    Returns:
      list : List of values for the field
    """
    # Parse annotations from seq_list records
    ann_iter = (parseAnnotation(s.description, delimiter=delimiter) for s in seq_iter)
    values = [a[field] for a in ann_iter]

    return list(set(values)) if unique else values


def annotationConsensus(seq_iter, field, delimiter=default_delimiter):
    """
    Calculate a consensus annotation for a set of sequences

    Arguments:
      seq_iter : an iterator or list of SeqRecord objects
      field : the annotation field to take a consensus of
      delimiter : a tuple of delimiters for (annotations, field/values, value lists)

    Returns:
      dict : Dictionary with keys
             `set` containing a list of unique annotation values,
             `count` containing annotation counts,
             `cons` containing the consensus annotation,
             `freq` containing the majority annotation frequency
    """
    # Define return dictionary
    cons_dict = {'set':None, 'count':None, 'cons':None, 'freq':None}

    # Parse annotations from seq_list records
    val_list = getAnnotationValues(seq_iter, field, delimiter=delimiter)

    # Define annotation set and counts
    cons_dict['set'] = sorted(set(val_list))
    cons_dict['count'] = [val_list.count(v) for v in cons_dict['set']]

    # Define consensus annotation
    i = cons_dict['count'].index(max(cons_dict['count']))
    cons_dict['cons'] = cons_dict['set'][i]
    cons_dict['freq'] = float(cons_dict['count'][i]) / len(val_list)

    return cons_dict


def convertGenericHeader(desc, delimiter=default_delimiter):
    """
    Converts any header to the pRESTO format

    Arguments:
      desc (str): a sequence description string.
      delimiter (tuple): a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: a dictionary of header field and value pairs.
    """
    # Replace whitespace and delimiter characters
    sub_regex = r'[%s\s]+' % re.escape(''.join(delimiter))
    conv = re.sub(sub_regex, '_', desc)
    try:
        # Check if modified header is valid
        header = parseAnnotation(conv, delimiter=delimiter)
    except:
        # Assign header to None if header cannot be converted
        header = None

    return header


def convert454Header(desc):
    """
    Parses 454 headers into the pRESTO format

    Arguments:
      desc (str): a sequence description string.

    Returns:
      dict: a dictionary of header field and value pairs.

    Examples:
      New style 454 header::

        @<accession> <length=##>
        @GXGJ56Z01AE06X length=222

      Old style 454 header::

        @<rank_x_y> <length=##> <uaccno=accession>
        @000034_0199_0169 length=437 uaccno=GNDG01201ARRCR
    """
    # Split description and assign field names
    try:
        # Build header dictionary
        fields = desc.split(' ')
        header = OrderedDict()
        header['ID'] = fields[0]
        header['LENGTH'] = fields[1].replace('length=', '')

        # Check for old format
        if len(fields) == 3:
            header['UACCNO'] = fields[2].replace('uaccno=', '')
        elif len(fields) != 2:
            raise ValueError
    except:
        header = None

    return header


def convertGenbankHeader(desc, delimiter=default_delimiter):
    """
    Converts GenBank and RefSeq headers into the pRESTO format

    Arguments:
      desc (str): a sequence description string.
      delimiter (tuple): a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: a dictionary of header field and value pairs.

    Examples:
      New style GenBank header::

        <accession>.<version> <description>
        >CM000663.2 Homo sapiens chromosome 1, GRCh38 reference primary assembly

      Old style GenBank header::

        gi|<GI record number>|<dbsrc>|<accession>.<version>|<description>
        >gi|568336023|gb|CM000663.2| Homo sapiens chromosome 1, GRCh38 reference primary assembly
    """
    # Define special characters to replace
    sub_regex = r'[%s\s]+' % re.escape(''.join(delimiter[1:]))

    # Split description and assign field names
    try:
        header = OrderedDict()

        # Try old format and fallback to new format if that fails
        fields = desc.split('|')
        if len(fields) == 5:
            header['ID'] = fields[3]
            header['GI'] = fields[1]
            header['SOURCE'] = fields[2]
            header['DESC'] = re.sub(sub_regex, '_', fields[4].strip())
        else:
            fields = desc.split(' ')
            header['ID'] = fields[0]
            header['DESC'] = re.sub(sub_regex, '_', '_'.join(fields[1:]).strip())
    except:
        header = None

    return header


def convertIlluminaHeader(desc):
    """
    Converts Illumina headers into the pRESTO format

    Arguments:
      desc (str): a sequence description string.

    Returns:
      dict: a dictionary of header field and value pairs.

    Examples:
      New style Illumina header::

        @<instrument>:<run number>:<flowcell ID>:<lane>:<tile>:<x-pos>:<y-pos> <read number>:<is filtered>:<control number>:<index sequence>
        @MISEQ:132:000000000-A2F3U:1:1101:14340:1555 2:N:0:ATCACG

      Old style Illumina header::

        @<instrument>:<flowcell lane>:<tile>:<x-pos>:<y-pos>#<index sequence>/<read number>
        @HWI-EAS209_0006_FC706VJ:5:58:5894:21141#ATCACG/1
        @MS6_33112:1:1101:18371:1066/1
    """
    # Split description and assign field names
    try:
        # Try new format and fallback to old if that fails
        fields = desc.split(' ')
        if len(fields) == 2:
            x = fields[1].split(':')
            index = x[3]
            read_num = x[0]
        elif '#' in desc:
            fields = desc.split('#')
            x = fields[1].split('/')
            index = x[0]
            read_num = x[1]
        else:
            fields = desc.split('/')
            index = None
            read_num = fields[1]

        # Build header dictionary
        header = OrderedDict()
        header['ID'] = fields[0]
        if index is not None:  header['INDEX'] = index
        header['READ'] = read_num
    except:
        header = None

    return header


def convertIMGTHeader(desc, simple=False):
    """
    Converts germline headers from IMGT/GENE-DB into the pRESTO format

    Arguments:
      desc (str): a sequence description string.
      simple (bool): if True then the header will be converted to only the allele name.

    Returns:
      dict: a dictionary of header field and value pairs.

    Examples:
      IMGT header::

        >X60503|IGHV1-18*02|Homo sapiens|F|V-REGION|142..417|276 nt|1| | | | |276+24=300|partial in 3'| |

      Header contains 15 fields separated by ``|`` (http://imgt.org/genedb):

        1. IMGT/LIGM-DB accession number(s).
        2. Gene and allele name.
        3. Species.
        4. Functionality.
        5. Exon(s), region name(s), or extracted label(s).
        6. Start and end positions in the IMGT/LIGM-DB accession number(s).
        7. Number of nucleotides in the IMGT/LIGM-DB accession number(s).
        8. Codon start, or 'NR' (not relevant) for non coding labels and
           out-of-frame pseudogenes.
        9. Number of nucleotides added in ``5'`` compared to the
           corresponding label extracted from IMGT/LIGM-DB.
        10. Number of nucleotides added or removed in ``3'``
            compared to the corresponding label extracted from IMGT/LIGM-DB.
        11. Number of added, deleted, and/or substituted
            nucleotides to correct sequencing errors, or 'not corrected' if
            non corrected sequencing errors.
        12. Number of amino acids (AA). This field indicates that the
            sequence is in amino acids.
        13. Number of characters in the sequence. Nucleotides (or AA) plus IMGT gaps.
        14. Partial (if it is).
        15. Reverse complementary (if it is).
    """
    # Split description and assign field names
    try:
        fields = desc.split('|')

        # Build header dictionary
        header = OrderedDict()
        header['ID'] = fields[1]

        if not simple:
            header['SPECIES'] = re.sub(r'\s', '_', fields[2])
            header['REGION'] = fields[4]
            header['FUNCTIONALITY'] = re.sub(r'[\(\)\[\]]', '', fields[3])
            header['PARTIAL'] = 'FALSE' if re.sub(r'\s', '', fields[13]) == '' else 'TRUE'
            header['ACCESSION'] = fields[0]

        # Position and length data
        #header['NUCLEOTIDES'] = re.sub('[^0-9]', '', fields[6])
        #header['LENGTH'] = fields[12].split('=')[1]
    except:
        header = None

    return header


def convertSRAHeader(desc):
    """
    Parses NCBI SRA or EMBL-EBI ENA headers into the pRESTO format

    Arguments:
      desc (str): a sequence description string.

    Returns:
      dict: a dictionary of header field and value pairs.

    Examples:
      Header from ``fastq-dump --split-files``::

        @<accession>.<spot> <original sequence description> <length=#>
        @SRR001666.1 071112_SLXA-EAS1_s_7:5:1:817:345 length=36
        @SRR1383326.1 1 length=250

      Header from ``fastq-dump --split-files -I``::

        @<accession>.<spot>.<read number> <original sequence description> <length=#>
        @SRR1383326.1.1 1 length=250

      Header from ENA::

        @<accession>.<spot> <original sequence description>
        @ERR220397.1 HKSQ1MM01DXT2W/3
        @ERR346596.1 BS-DSFCONTROL04:4:000000000-A3F0Y:1:1101:12758:1640/1
        @ERR346596.1 BS-DSFCONTROL04:4:000000000-A3F0Y:1:1101:12758:1640/2
    """
    # Split description and assign field names
    try:
        fields = desc.split(' ')

        # Build header dictionary
        header = OrderedDict()

        # Check for read number if sequence id
        read_id = fields[0].split('.')
        if len(read_id) == 3:
            header['ID'] = '.'.join(read_id[:2])
            header['READ'] = read_id[2]
        else:
            header['ID'] = fields[0]

        header['DESC'] = fields[1]
        if len(fields) >= 3 and 'length' in fields[2]:
            header['LENGTH'] = fields[2].replace('length=', '')
    except:
        header = None

    return header


def convertMIGECHeader(desc):
    """
    Parses headers from the MIGEC tool into the pRESTO format

    Arguments:
      desc (str): a sequence description string.

    Returns:
      dict: a dictionary of header field and value pairs.

    Examples:
      MIGEC header::

        @MIG UMI:<UMI sequence>:<consensus read count>
        @MIG UMI:TCGGCCAACAAA:8
    """
    # Split description and assign field names
    try:
        fields = desc.split(':')

        # Build header dictionary
        header = OrderedDict()
        header['ID'] = fields[1]
        header['COUNT'] = fields[2]
    except:
        header = None

    return header


def addHeader(header, fields, values, delimiter=default_delimiter):
    """
    Adds fields and values to a sequence header

    Arguments:
      header : an annotation dictionary returned by parseAnnotation.
      fields : the list of fields to add or append to.
      values : the list of annotation values to add for each field.
      delimiter : a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: modified header dictionary.
    """
    for f, v in zip(fields, values):
        header = mergeAnnotation(header, {f:v}, delimiter=delimiter)

    return header


def collapseHeader(header, fields, actions, delimiter=default_delimiter):
    """
    Collapses a sequence header

    Arguments:
      header : an annotation dictionary returned by parseAnnotation.
      fields : the list of fields to collapse.
      actions : the list of collapse action take;
                one of (max, min, sum, first, last, set, cat) for each field.
      delimiter : a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: modified header dictionary.
    """
    for f, a in zip(fields, actions):
        header = collapseAnnotation(header, a, f, delimiter=delimiter)

    return header


def copyHeader(header, fields, names, actions=None, delimiter=default_delimiter):
    """
    Copies fields in a sequence header

    Arguments:
      header : an annotation dictionary returned by parseAnnotation.
      fields : a list of the field names to copy.
      names : a list of the new field names.
      actions : the list of collapse action take after the copy;
                one of (max, min, sum, first, last, set, cat) for each field.
      delimiter : a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: modified header dictionary.
    """
    old_header = header.copy()
    for f, n in zip(fields, names):
        header = mergeAnnotation(header, {n: old_header[f]}, delimiter=delimiter)

    if actions is not None:
        header = collapseHeader(header, names, actions, delimiter=delimiter)

    return header


def deleteHeader(header, fields, delimiter=default_delimiter):
    """
    Deletes fields from a sequence header

    Arguments:
      header : an annotation dictionary returned by parseAnnotation.
      fields : the list of fields to delete.
      delimiter : a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: modified header dictionary
    """
    for f in fields:  del header[f]

    return header


def expandHeader(header, fields, separator=default_separator,
                 delimiter=default_delimiter):
    """
    Splits and annotation value into separate fields in a sequence header

    Arguments:
      header : an annotation dictionary returned by parseAnnotation.
      fields : the field to split.
      separator : the delimiter to split the values by.
      delimiter : a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: modified header dictionary.
    """
    for f in fields:
        values = header[f].split(separator)
        names = [f + str(i + 1) for i in range(len(values))]
        ann = OrderedDict([(n, v) for n, v in zip(names, values)])
        header = mergeAnnotation(header, ann, delimiter=delimiter)
        del header[f]

    return header


def mergeHeader(header, fields, name, action=None, delete=False,
                delimiter=default_delimiter):
    """
    Merges fields in a sequence header

    Arguments:
      header : an annotation dictionary returned by parseAnnotation.
      fields : a list of the field names to merge.
      name : the name of the new field.
      delete : if True delete the merged fields.
      actions : the list of collapse action take after the merge
                one of (max, min, sum, first, last, set, cat).
      delimiter : a tuple of delimiters for (fields, values, value lists)

    Returns:
      dict: modified header dictionary.
    """
    merge = {name: [header[f] for f in fields]}
    header = mergeAnnotation(header, merge, delimiter=delimiter)

    # Delete fields
    if delete:
        for f in fields:
            if f != name:  del header[f]

    # Collapse action
    if action is not None:
        header = collapseHeader(header, fields=[name], actions=[action],
                                delimiter=delimiter)

    return header


def renameHeader(header, fields, names, actions=None, delimiter=default_delimiter):
    """
    Renames fields in a sequence header

    Arguments:
      header : an annotation dictionary returned by parseAnnotation.
      fields : a list of the current field names.
      names : a list of the new field names.
      actions : the list of collapse action take after the rename;
              one of (max, min, sum, first, last, set, cat) for each field.
      delimiter : a tuple of delimiters for (fields, values, value lists).

    Returns:
      dict: modified header dictionary.
    """
    for f, n in zip(fields, names):
        header = renameAnnotation(header, f, n, delimiter=delimiter)

    if actions is not None:
        header = collapseHeader(header, names, actions, delimiter=delimiter)

    return header
