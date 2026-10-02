"""
Sequence processing functions
"""
# Info
from copy import deepcopy

__author__ = 'Jason Anthony Vander Heiden'
from presto import __version__, __date__, default_delimiter

# Imports
import numpy as np
import pandas as pd
import re
import math
from collections import OrderedDict
from itertools import product, zip_longest, groupby
from scipy import stats as stats
from Bio import Align
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord

# Presto imports
from presto.Defaults import default_delimiter, default_barcode_field, default_primer_field, \
                            default_gap_chars, default_mask_chars, default_missing_chars, \
                            default_consensus_min_freq, default_consensus_min_qual, \
                            default_primer_gap_penalty, default_primer_max_error, \
                            default_primer_max_len, default_primer_start, \
                            default_filter_min_qual, default_filter_min_len, default_filter_max_missing, \
                            default_filter_max_repeat, default_filter_window, \
                            default_assembly_alpha, default_assembly_max_error, default_assembly_min_ident, \
                            default_assembly_min_len, default_assembly_max_len, \
                            default_assembly_gap, default_assembly_evalue, default_assembly_max_hits, \
                            default_usearch_exec
from presto.Annotation import parseAnnotation, flattenAnnotation, mergeAnnotation, annotationConsensus
from presto.Applications import runBlastn, runUBlast
from presto.IO import printWarning, printError
from presto.Multiprocessing import SeqResult

# Constants
# default_dna_matrix = getDNAScoreDict(mask_score=(0, 1), gap_score=(0, 0))
# default_aa_matrix = getAAScoreDict(mask_score=(0, 1), gap_score=(0, 0))

class PrimerAlignment:
    """
    A class defining a primer alignment result
    """
    # Instantiation
    def __init__(self, seq=None):
        """
        Initializer

        Arguments:
          seq : Bio.SeqRecord.SeqRecord object contained the sequence primers were aligned against.

        Returns:
          presto.Sequence.PrimerAlignment
        """
        self.seq = seq
        self.primer = None
        self.align_seq = None
        self.align_primer = None
        self.start = None
        self.end = None
        self.gaps = 0
        self.error = 1
        self.rev_primer = False
        self.valid = False

    # Set boolean evaluation to valid value
    def __bool__(self):
        """
        Boolean evaluation of the alignment

        Returns:
          int :  evaluates to the value of the valid attribute
        """
        return self.valid

    # Set length evaluation to length of alignment
    def __len__(self):
        """
        Length of alignment

        Returns:
          int : length of align_seq attribute
        """
        if self.align_seq is None:
            return 0
        else:
            return len(self.align_seq)



class AssemblyRecord:
    """
    A class defining a paired-end assembly result
    """
    # Instantiation
    def __init__(self, seq=None):
        self.seq = seq
        self.ref_seq = None
        self.head_pos = None
        self.tail_pos = None
        self.ref_pos = None
        self.gap = None
        self.zscore = float('-inf')
        self.pvalue = None
        self.evalue = None
        self.error = None
        self.ident = None
        self.valid = False

    # Set boolean evaluation to valid value
    def __bool__(self):
        return self.valid

    # Set length evaluation to length of SeqRecord
    def __len__(self):
        if self.seq is None:
            return 0
        else:
            return len(self.seq)

    # Set overlap length to head_pos difference
    @property
    def overlap(self):
        if self.head_pos is None:
            return None
        else:
            return self.head_pos[1] - self.head_pos[0]


class AssemblyStats:
    """
    Class containing p-value and z-score matrices for scoring assemblies
    """
    # Instantiation
    def __init__(self, n):
        self.p = AssemblyStats._getPMatrix(n)
        self.z = AssemblyStats._getZMatrix(n)
        #print self.z

    @staticmethod
    def _getPMatrix(n):
        """
        Generates a matrix of mid-p correct p-values from a binomial distribution

        Arguments:
        n = maximum trials

        Returns:
        a numpy.array of successes by trials p-values
        """
        p_matrix = np.empty([n, n], dtype=float)
        p_matrix.fill(np.nan)
        k = np.arange(n, dtype=int)
        for i, x in enumerate(k):
            p_matrix[x, i:] = 1 - stats.binom.cdf(x - 1, k[i:], 0.25) - stats.binom.pmf(x, k[i:], 0.25) / 2.0

        return p_matrix

    @staticmethod
    def _getZMatrix(n):
        """
        Generates a matrix of z-score approximations for a binomial distribution

        Arguments:
        n = maximum trials

        Returns:
        a numpy.array of successes by trials z-scores
        """
        z_matrix = np.empty([n, n], dtype=float)
        z_matrix.fill(np.nan)
        k = np.arange(0, n, dtype=int)
        for i, x in enumerate(k):
            j = i + 1 if i == 0 else i
            z_matrix[x, j:] = (x - k[j:]/4.0)/np.sqrt(3.0/16.0*k[j:])

        return z_matrix


def translateAmbigDNA(key):
    """
    Translates IUPAC ambiguous nucleotide characters to or from character sets

    Arguments:
      key : String or re.search object containing the character set to translate

    Returns:
      str : Character translation
    """
    # Define valid characters and character translations
    IUPAC_uniq = '-.ACGT'
    IUPAC_ambig = 'UBDHKMNRSVWY'
    IUPAC_trans = {'AG':'R', 'CT':'Y', 'CG':'S', 'AT':'W', 'GT':'K', 'AC':'M',
                   'CGT':'B', 'AGT':'D', 'ACT':'H', 'ACG':'V', 'ACGTUBDHKMRSVWY':'N',
                   'T':'U', '-.':'.'}

    # Convert passed regular expression match to a string
    if hasattr(key, 'group'): key = key.group(1)

    # Sort character in alphabetic order
    key = ''.join(sorted(key))

    # Return input character if no translation needed
    if len(key) == 1 and key in IUPAC_uniq:
        return key
    # Return regular expression string for ambiguous single character
    elif len(key) == 1 and key in IUPAC_ambig:
        return ['[' + k + ']' for k, v in IUPAC_trans.items() if v == key][0]
    # Return single ambiguous character for character set
    elif key in IUPAC_trans:
        return IUPAC_trans[key]
    else:
        return 'N'


def scoreDNA(a, b, mask_score=None, gap_score=None):
    """
    Returns the score for a pair of IUPAC ambiguous nucleotide characters

    Arguments:
      a : First character
      b : Second character
      n_score : Tuple of length two defining scores for all matches against an N
                character for (a, b), with the score for character (a) taking precedence;
                if None score symmetrically according to IUPAC character identity
      gap_score : Tuple of length two defining score for all matches against a gap (-, .)
                  character for (a, b), with the score for character (a) taking precedence;
                  if None score symmetrically according to IUPAC character identity

    Returns:
      int : Score for the character pair
    """
    # Define ambiguous character translations
    IUPAC_trans = {'AGWSKMBDHV':'R', 'CTUSWKMBDHV':'Y', 'CGKMBDHV':'S', 'ATUKMBDHV':'W', 'GTUBDHV':'K',
                   'ACBDHV':'M', 'CGTUDHV':'B', 'AGTUHV':'D', 'ACTUV':'H', 'ACG':'V', 'ACGTUBDHKMRSVWY':'N',
                   'T':'U', '-.':'.'}

    # Create list of tuples of synonymous character pairs
    IUPAC_matches = [p for k, v in IUPAC_trans.items() for p in list(product(k, v))]

    # Check gap and N-value conditions, prioritizing score for first character
    if gap_score is not None and a in '-.':
        return gap_score[0]
    elif mask_score is not None and a in 'nN':
        return mask_score[0]
    elif gap_score is not None and b in '-.':
        return gap_score[1]
    elif mask_score is not None and b in 'nN':
        return mask_score[1]

    # Return symmetric and reflexive score for IUPAC match conditions
    if a == b:
        return 1
    elif (a, b) in IUPAC_matches:
        return 1
    elif (b, a) in IUPAC_matches:
        return 1
    else:
        return 0


def scoreAA(a, b, mask_score=None, gap_score=None):
    """
    Returns the score for a pair of IUPAC Extended Protein characters

    Arguments:
      a : First character
      b : Second character
      mask_score : Tuple of length two defining scores for all matches against an X
                   character for (a, b), with the score for character (a) taking precedence;
                   if None score symmetrically according to IUPAC character identity
      gap_score : Tuple of length two defining score for all matches against a gap (-, .)
                  character for (a, b), with the score for character (a) taking precedence;
                  if None score symmetrically according to IUPAC character identity

    Returns:
      int : Score for the character pair
    """
    # Define ambiguous character translations
    IUPAC_trans = {'RN':'B', 'EQ':'Z', 'LI':'J', 'ABCDEFGHIJKLMNOPQRSTUVWYZ':'X',
                   '-.':'.'}
    # Create list of tuples of synonymous character pairs
    IUPAC_matches = [p for k, v in IUPAC_trans.items() for p in list(product(k, v))]

    # Check gap and X-value conditions, prioritizing score for first character
    if gap_score is not None and a in '-.':
        return gap_score[0]
    elif mask_score is not None and a in 'xX':
        return mask_score[0]
    elif gap_score is not None and b in '-.':
        return gap_score[1]
    elif mask_score is not None and b in 'xX':
        return mask_score[1]

    # Return symmetric and reflexive score for IUPAC match conditions
    if a == b:
        return 1
    elif (a, b) in IUPAC_matches:
        return 1
    elif (b, a) in IUPAC_matches:
        return 1
    else:
        return 0


def getDNAScoreDict(mask_score=None, gap_score=None):
    """
    Generates a score dictionary

    Arguments:
      mask_score : Tuple of length two defining scores for all matches against an N
                   character for (a, b), with the score for character (a) taking precedence;
                   if None score symmetrically according to IUPAC character identity
      gap_score : Tuple of length two defining score for all matches against a [-, .]
                  character for (a, b), with the score for character (a) taking precedence;
                  if None score symmetrically according to IUPAC character identity

    Returns:
      dict : Score dictionary with keys (char1, char2) mapping to scores
    """
    chars = '-.ACGTURYSWKMBDHVN'
    score_dict = {k:scoreDNA(*k, mask_score=mask_score, gap_score=gap_score)
                  for k in product(chars, repeat=2)}

    return score_dict


def getAAScoreDict(mask_score=None, gap_score=None):
    """
    Generates a score dictionary

    Arguments:
      mask_score : Tuple of length two defining scores for all matches against an X
                   character for (a, b), with the score for character (a) taking precedence;
                   if None score symmetrically according to IUPAC character identity
      gap_score : Tuple of length two defining score for all matches against a [-, .]
                  character for (a, b), with the score for character (a) taking precedence;
                  if None score symmetrically according to IUPAC character identity

    Returns:
      dict : Score dictionary with keys (char1, char2) mapping to scores
    """
    chars = '-.*ABCDEFGHIJKLMNOPQRSTUVWXYZ'
    score_dict = {k:scoreAA(*k, mask_score=mask_score, gap_score=gap_score)
                  for k in product(chars, repeat=2)}

    return score_dict


def reverseComplement(seq):
    """
    Takes the reverse complement of a sequence

    Arguments:
      seq : a SeqRecord object, Seq object or string to reverse complement

    Returns:
      Seq : Object of the same type as the input with the reverse complement sequence
    """

    if isinstance(seq, SeqRecord):
        new_record = seq.reverse_complement(id=True, name=True, description=True,
                                            features=True, annotations=True,
                                            letter_annotations=True)
        #new_record.annotations['orientation'] = 'RC'
    elif isinstance(seq, Seq):
        new_record = seq.reverse_complement()
    elif isinstance(seq, str):
        new_record = str(Seq(seq).reverse_complement())
    else:
        printError('Invalid record type passed to reverseComplement.')

    return new_record


def checkSeqEqual(seq1, seq2, ignore_chars=default_missing_chars):
    """
    Determine if two sequences are equal, excluding missing positions

    Arguments:
      seq1 : SeqRecord object
      seq2 : SeqRecord object
      ignore_chars : Set of characters to ignore

    Returns:
      bool : True if the sequences are equal
    """
    equal = True
    #for a, b in zip(seq1.upper(), seq2.upper()):
    for a, b in zip_longest(seq1, seq2):
        if a != b and a not in ignore_chars and b not in ignore_chars:
            equal = False
            break

    return equal


# TODO:  can be removed I think.
def weightSeq(seq, ignore_chars=set()):
    """
    Returns the length of a sequencing excluding ignored characters

    Arguments:
      seq : SeqRecord or Seq object
      ignore_chars : Set of characters to ignore when counting sequence length

    Returns:
      int : Sum of the character scores for the sequence
    """
    return sum(1 for x in seq if x not in ignore_chars)


def scoreSeqPair(seq1, seq2, ignore_chars=set(), score_dict=getDNAScoreDict()):
    """
    Determine the error rate for a pair of sequences

    Arguments:
      seq1 : SeqRecord object
      seq2 : SeqRecord object
      ignore_chars : Set of characters to ignore when scoring and counting the weight
      score_dict : Optional dictionary of alignment scores

    Returns:
      Tuple : Tuple of the (score, minimum weight, error rate) for the pair of sequences
    """
    # TODO:  remove upper calls for speed. maybe by extending score dict with lowercase.
    # Determine score
    chars = list(zip(seq1.upper(), seq2.upper()))
    score_list = [score_dict[(a, b)] for a, b in chars \
                  if a not in ignore_chars and b not in ignore_chars]
    score = sum(score_list)
    weight = len(score_list)
    error = 1.0 - float(score) / weight if weight > 0 else 1.0

    return (score, weight, error)


def calculateDiversity(seq_list, score_dict=getDNAScoreDict()):
    """
    calculateDiversity(seq_list, score_dict=getDNAScoreDict())

    Determine the average pairwise error rate for a list of sequences

    Arguments:
      seq_list : List of SeqRecord objects to score
      score_dict : Optional dictionary of alignment scores as {(char1, char2): score}

    Returns:
      float : Average pairwise error rate for the list of sequences
    """
    # Return 0 if less than 2 sequences
    if len(seq_list) <= 1:
        return 0

    scores = []
    for i, seq1 in enumerate(seq_list):
        for seq2 in seq_list[(i + 1):]:
            scores.append(scoreSeqPair(seq1, seq2, score_dict=score_dict)[2])

    return sum(scores) / len(scores)


def calculateSetError(seq_list, ref_seq, ignore_chars=default_mask_chars,
                      score_dict=getDNAScoreDict()):
    """
    calculateSetError(seq_list, ref_seq, ignore_chars=['n', 'N'], score_dict=getDNAScoreDict())

    Counts the occurrence of nucleotide mismatches from a reference in a set of sequences

    Arguments:
      seq_list : list of SeqRecord objects with aligned sequences.
      ref_seq : SeqRecord object containing the reference sequence to match against.
      ignore_chars : list of characters to exclude from mismatch counts.
      score_dict : optional dictionary of alignment scores as {(char1, char2): score}.

    Returns:
      float : error rate for the set.
    """
    # Count informative characters in reference sequence
    ref_bases = sum(1 for b in ref_seq if b not in ignore_chars)

    # Return 0 mismatches for single record case
    if len(seq_list) <= 1:
        return 0.0

    # Iterate over seq_list and count mismatches
    total, score = 0, 0
    for seq in seq_list:
        seq_bases = sum(1 for a in seq if a not in ignore_chars)
        total += min(seq_bases, ref_bases)
        score += sum([score_dict[(a, b)] for a, b in zip(seq, ref_seq)
                      if a not in ignore_chars and b not in ignore_chars])

    # Calculate and return error rate
    try:
        return 1.0 - float(score) / total
    except ZeroDivisionError:
        return 1.0


def deleteSeqPositions(seq, positions):
    """
    Deletes a list of positions from a SeqRecord

    Arguments:
      seq : SeqRecord objects
      positions : Set of positions (indices) to delete

    Returns:
      SeqRecord : Modified SeqRecord with the specified positions removed
    """
    seq_del = ''.join([x for i, x in enumerate(seq.seq) if i not in positions])
    record = SeqRecord(Seq(seq_del), id=seq.id, name=seq.name, description=seq.description)

    if 'phred_quality' in seq.letter_annotations:
        qual_del = [x for i, x in enumerate(seq.letter_annotations['phred_quality']) \
                    if i not in positions]
        record.letter_annotations['phred_quality'] = qual_del

    return record


def findGapPositions(seq_list, max_gap, gap_chars=default_gap_chars):
    """
    Finds positions in a set of aligned sequences with a high number of gap characters.

    Arguments:
      seq_list : List of SeqRecord objects with aligned sequences
      max_gap : Float of the maximum gap frequency to consider a position as non-gapped
      gap_chars : Set of characters to consider as gaps

    Returns:
      list : Positions (indices) with gap frequency greater than max_gap
    """
    # Return an empty list in the singleton case
    seq_count = float(len(seq_list))
    if seq_count == 1:
        return []

    # Iterate through positions and count gaps
    gap_positions = []
    seq_str = [str(s.seq) for s in seq_list]
    for i, chars in enumerate(zip_longest(*seq_str, fillvalue='-')):
        gap_count = sum([chars.count(c) for c in gap_chars])
        gap_freq = gap_count / seq_count

        # Update gap position over threshold
        if gap_freq > max_gap:
            gap_positions.append(i)

    return gap_positions


def qualityConsensus(seq_list, min_qual=default_consensus_min_qual, min_freq=default_consensus_min_freq,
                     dependent=False, ignore_chars=default_missing_chars):
    """
    Builds a consensus sequence from a set of sequences

    Arguments:
      seq_list : List of SeqRecord objects
      min_qual : Quality cutoff to assign a base
      min_freq : Frequency cutoff to assign a base
      dependent : If False assume sequences are independent for quality calculation
      ignore_chars : Set of characters to exclude when building a consensus sequence

    Returns:
      SeqRecord : Consensus SeqRecord object
    """
    # Return a copy of the input SeqRecord upon singleton
    if len(seq_list) == 1:
        seq = seq_list[0]
        # Mask low quality nucleotides
        seq_str = str(seq.seq)
        quals = seq.letter_annotations['phred_quality']
        seq_mask = [seq_str[i] if q >= min_qual else 'N' for i, q in enumerate(quals)]
        seq = SeqRecord(Seq(''.join(seq_mask)),
                        id=seq.id,
                        name=seq.name,
                        description=seq.description,
                        letter_annotations=seq.letter_annotations)
        return seq

    # Create sequence and annotation iterators
    # Pad unequal length sequences with character '-' and quality 0
    seq_str = [str(s.seq) for s in seq_list]
    seq_iter = zip_longest(*seq_str, fillvalue='-')
    ann_list = [s.letter_annotations['phred_quality'] for s in seq_list]
    ann_iter = zip_longest(*ann_list, fillvalue=0)

    # Build consensus
    consensus_seq = []
    consensus_qual = []
    for chars, quals in zip(seq_iter, ann_iter):
        # Define set of non-missing characters
        char_set = set(chars).difference(ignore_chars)

        # Assign N if no missing characters and proceed to next position
        if not char_set:
            consensus_seq.append('N')
            consensus_qual.append(0)
            continue

        # Define non-missing character frequencies
        char_count = float(len([c for c in chars if c in char_set]))
        char_freq = {c: chars.count(c) / char_count for c in char_set}

        # Create per character quality sets and quality sums
        qual_total = float(sum(quals))
        if qual_total == 0:  qual_total = 1
        qual_set, qual_sum = {}, {}
        for c in char_set:
            qual_set[c] = [q for i, q in enumerate(quals) if chars[i] == c]
            qual_sum[c] = sum(qual_set[c])

        # TODO: write unit test and verify quality score calculation for sets with missing data
        # Calculate per character consensus quality scores
        if dependent:
            qual_cons = {c: int(max(qual_set[c]) * qual_sum[c] / qual_total)
                         for c in qual_set}
        else:
            qual_cons = {c: int(qual_sum[c] * qual_sum[c] / qual_total)
                         for c in qual_set}

        # Select character with highest consensus quality
        cons = sorted([(c, min(q, 90)) for c, q in qual_cons.items() \
                if q == max(qual_cons.values())])[0]
        
        # Assign N if consensus quality or frequency threshold is failed
        if cons[1] < min_qual or char_freq[cons[0]] < min_freq:
            cons = ('N', 0)

        # Assign consensus base and quality
        consensus_seq.append(cons[0])
        consensus_qual.append(cons[1])

    # Define return SeqRecord
    record = SeqRecord(Seq(''.join(consensus_seq)),
                       id='consensus',
                       name='consensus',
                       description='',
                       letter_annotations={'phred_quality':consensus_qual})

    return record


def frequencyConsensus(seq_list, min_freq=default_consensus_min_freq,
                       ignore_chars=default_missing_chars):
    """
    Builds a consensus sequence from a set of sequences

    Arguments:
      set_seq : List of SeqRecord objects
      min_freq : Frequency cutoff to assign a base
      ignore_chars : Set of characters to exclude when building a consensus sequence


    Returns:
      SeqRecord : Consensus SeqRecord object
    """
    # Return a copy of the input SeqRecord upon singleton
    if len(seq_list) == 1:
        return seq_list[0]

    # Build consensus
    seq_str = [str(s.seq) for s in seq_list]
    consensus_seq = []
    for chars in zip_longest(*seq_str, fillvalue='-'):
        # Define set of non-missing characters
        char_set = set(chars).difference(ignore_chars)

        # Assign N if no non-missing characters and proceed to next position
        if not char_set:
            consensus_seq.append('N')
            continue

        # Define non-missing character frequencies
        char_count = float(len([c for c in chars if c in char_set]))
        char_freq = {c: chars.count(c) / char_count for c in char_set}
        freq_max = max(char_freq.values())

        # Assign consensus as most frequent character
        cons = sorted([c if char_freq[c] >= min_freq else 'N' \
                for c in char_set if char_freq[c] == freq_max])[0]
        
        consensus_seq.append(cons)

    # Define return SeqRecord
    record = SeqRecord(Seq(''.join(consensus_seq)),
                       id='consensus',
                       name='consensus',
                       description='')

    return record


def indexSeqSets(seq_dict, field=default_barcode_field, delimiter=default_delimiter):
    """
    Identifies sets of sequences with the same ID field

    Arguments:
      seq_dict : a dictionary index of sequences returned from SeqIO.index()
      field : the annotation field containing set IDs
      delimiter : a tuple of delimiters for (fields, values, value lists)

    Returns:
      dict : Dictionary mapping set name to a list of record names
    """
    set_dict = {}
    for key, rec in seq_dict.items():
        tag = parseAnnotation(rec.description, delimiter=delimiter)[field]
        set_dict.setdefault(tag, []).append(key)

    return set_dict


def subsetSeqSet(seq_iter, field, values, delimiter=default_delimiter):
    """
    Subsets a sequence set by annotation value

    Arguments:
      seq_iter : Iterator or list of SeqRecord objects
      field : Annotation field to select by
      values : List of annotation values that define the retained sequences
      delimiter : Tuple of delimiters for (annotations, field/values, value lists)

    Returns:
      list : Modified list of SeqRecord objects
    """
    # Parse annotations from seq_list records
    ann_list = [parseAnnotation(s.description, delimiter=delimiter) for s in seq_iter]

    # Subset seq_list by annotation
    if not isinstance(values, list):  values = [values]
    seq_subset = [seq_iter[i] for i, a in enumerate(ann_list) if a[field] in values]

    return seq_subset


def subsetSeqIndex(seq_dict, field, values, delimiter=default_delimiter):
    """
    Subsets a sequence set by annotation value

    Arguments:
      seq_dict : Dictionary index of sequences returned from SeqIO.index()
      field : Annotation field to select keys by
      values : List of annotation values that define the retained keys
      delimiter : Tuple of delimiters for (annotations, field/values, value lists)

    Returns:
      list : List of keys
    """
    # Parse annotations from seq_dict and subset keys
    key_subset = [k for k in seq_dict \
                  if parseAnnotation(seq_dict[k].description, delimiter=delimiter)[field] \
                  in values]

    return key_subset


def compilePrimers(primers):
    """
    Translates IUPAC Ambiguous Nucleotide characters to regular expressions and compiles them

    Arguments:
      key : Dictionary of sequences to translate

    Returns:
      dict : Dictionary of compiled regular expressions
    """

    primers_regex = {k: re.compile(re.sub(r'([RYSWKMBDHVN])', translateAmbigDNA, v))
                     for k, v in primers.items()}

    return primers_regex


def localAlignment(seq_record, primers, primers_regex=None, max_error=default_assembly_max_error,
                   max_len=default_assembly_max_len, rev_primer=False, skip_rc=False,
                   gap_penalty=default_primer_gap_penalty,
                   score_dict=getDNAScoreDict(mask_score=(0, 1), gap_score=(0, 0))):
    """
    Performs pairwise local alignment of a list of short sequences against a long sequence

    Arguments:
      seq_record : a SeqRecord object to align primers against
      primers : dictionary of {names: short IUPAC ambiguous sequence strings}
      primers_regex : optional dictionary of {names: compiled primer regular expressions}
      max_error : maximum acceptable error rate before aligning reverse complement
      max_len : maximum length of sample sequence to align
      rev_primer : if True align with the tail end of the sequence
      skip_rc : if True do not check reverse complement sequences
      gap_penalty : a tuple of positive (gap open, gap extend) penalties
      score_dict : optional dictionary of alignment scores as {(char1, char2): score}

    Returns:
      presto.Sequence.PrimerAlignment : primer alignment result object
    """
    # Defined undefined parameters
    if primers_regex is None:  primers_regex = compilePrimers(primers)
    seq_record = seq_record.upper()
    rec_len = len(seq_record)
    max_len = min(rec_len, max_len)

    # Create empty return object
    align = PrimerAlignment(seq_record)
    align.rev_primer = rev_primer

    # Define sequences to align and assign orientation tags
    if not skip_rc:
        seq_list = [seq_record, reverseComplement(seq_record)]
        seq_list[0].annotations['seqorient'] = 'F'
        seq_list[1].annotations['seqorient'] = 'RC'
    else:
        seq_list = [seq_record]
        seq_list[0].annotations['seqorient'] = 'F'

    # Attempt regular expression match first
    for rec in seq_list:
        scan_seq = str(rec.seq)
        scan_seq = scan_seq[:max_len] if not rev_primer else scan_seq[-max_len:]
        for adpt_id, adpt_regex in primers_regex.items():
            adpt_match = adpt_regex.search(scan_seq)
            # Parse matches
            if adpt_match:
                align.seq = rec
                align.primer = adpt_id
                align.align_seq = scan_seq
                align.align_primer = '-' * adpt_match.start(0) + \
                                     primers[adpt_id] + \
                                     '-' * (max_len - adpt_match.end(0))
                align.gaps = 0
                align.error = 0
                align.valid = True

                # Determine start and end positions
                if not rev_primer:
                    align.start = adpt_match.start(0)
                    align.end = adpt_match.end(0)
                else:
                    rev_pos = rec_len - max_len
                    align.start = adpt_match.start(0) + rev_pos
                    align.end = adpt_match.end(0) + rev_pos

                return align


    # Perform local alignment if regular expression match fails
    sub_matrix = Align.substitution_matrices.Array(data=score_dict)
    best_align, best_rec, best_adpt, best_error = None, None, None, None
    for rec in seq_list:
        this_align = dict()
        scan_seq = str(rec.seq)
        scan_seq = scan_seq[:max_len] if not rev_primer else scan_seq[-max_len:]
        for adpt_id, adpt_seq in primers.items():
            pw_aligner = Align.PairwiseAligner(mode='local',
                                               substitution_matrix=sub_matrix,
                                               open_gap_score = -gap_penalty[0],
                                               extend_gap_score = -gap_penalty[1])
            pw2_align = pw_aligner.align(scan_seq, adpt_seq)
            if pw2_align:
                this_align.update({adpt_id: pw2_align[0]})
        if not this_align:  continue

        # Determine alignment with lowest error rate
        for x_adpt, x_align in this_align.items():
            x_error = 1.0 - x_align.score / len(primers[x_adpt])
            if best_error is None or x_error < best_error:
                best_align = this_align
                best_rec = rec
                best_adpt = x_adpt
                best_error = x_error

        # Skip rev_primer complement if forward sequence error within defined threshold
        if best_error <= max_error:  break

    # Set return object to lowest error rate alignment
    if best_align:
        align_top = best_align[best_adpt]
        align_coord = align_top.coordinates
        align_primer = align_top.query
        align_gaps = align_top.counts().gaps
        align_str = align_top.format("fasta").replace('\n', '').split('>')[1:]

        # Populate return object
        align.seq = best_rec
        align.primer = best_adpt
        align.align_seq = align_top.target[:align_coord[0][0]] + \
                          align_str[0] + \
                          align_top.target[align_coord[0][-1]:]
        align.align_primer = '-' * align_coord[0][0] + \
                             align_str[1] + \
                             '-' * len(align_top.target[align_coord[0][-1]:])
        align.gaps = align_gaps
        align.error = best_error
        align.valid = True

        # Determine start and end positions
        if not rev_primer:
            align.start = align_coord[0][0]
            align.end = align_coord[0][-1]
        else:
            # Count position from tail and end gaps
            rev_pos = rec_len - max_len if rec_len > max_len else 0
            align.start = rev_pos + align_coord[0][0]
            align.end = rev_pos + align_coord[0][-1]

    return align


def scoreAlignment(seq_record, primers, start=default_primer_start, rev_primer=False,
                   score_dict=getDNAScoreDict(mask_score=(0, 1), gap_score=(0, 0))):
    """
    Performs a simple fixed position alignment of primers

    Arguments:
      seq_record : a SeqRecord object to align primers against
      primers : dictionary of {names: short IUPAC ambiguous sequence strings}
      start : position where primer alignment starts
      rev_primer : if True align with the tail end of the sequence
      score_dict : optional dictionary of {(char1, char2): score} alignment scores

    Returns:
      presto.Sequence.PrimerAlignment : primer alignment result object
    """
    # Create empty return dictionary
    seq_record = seq_record.upper()
    align = PrimerAlignment(seq_record)
    align.rev_primer = rev_primer
    align.rev_seq = False

    # Score primers
    this_align = {}
    rec_len = len(seq_record)
    if rev_primer:  end = rec_len - start
    for adpt_id, adpt_seq in primers.items():
        if rev_primer:
            start = end - len(adpt_seq)
        else:
            end = start + len(adpt_seq)
        chars = zip(seq_record[start:end], adpt_seq)
        score = sum([score_dict[(c1, c2)] for c1, c2 in chars])
        this_align.update({adpt_id: (score, start, end)})

    # Determine primer with lowest error rate
    best_align, best_adpt, best_err = None, None, None
    for adpt, algn in this_align.items():
        # adpt_err = 1.0 - float(algn[0]) / weightSeq(primers[adpt])
        err = 1.0 - float(algn[0]) / len(primers[adpt])
        if best_err is None or err < best_err:
            best_align = algn
            best_adpt = adpt
            best_err = err

    # Set return dictionary to lowest error rate alignment
    if best_align:
        # Populate return object
        align.primer = best_adpt if best_err < 1.0 else None
        align.start = best_align[1]
        align.end = best_align[2]
        align.error = best_err
        align.valid = True

        # Determine alignment sequences
        if not rev_primer:
            align.align_seq = str(seq_record.seq[:best_align[2]])
            align.align_primer = '-' * best_align[1] + primers[best_adpt]
        else:
            align.align_seq = str(seq_record.seq[best_align[1]:])
            align.align_primer = primers[best_adpt] + '-' * (rec_len - best_align[2])

    return align


def extractAlignment(seq_record, start, length, rev_primer=False):
    """
    Extracts a subsequence from sequence

    Arguments:
      data : SeqRecord to process.
      start : position where subsequence starts.
      length : the length of the subsequence to extract.
      rev_primer : if True extract relative to the tail end of the sequence.

    Returns:
      presto.Sequence.PrimerAlignment : extraction results as an alignment object
    """
    # Create empty return dictionary
    seq_record = seq_record.upper()
    align = PrimerAlignment(seq_record)
    align.rev_primer = rev_primer

    rec_len = len(seq_record)
    if rev_primer:
        end = rec_len - start
        start = end - length
    else:
        end = start + length

    # Extract region
    region = str(seq_record.seq[start:end])

    # Populate return object
    align.primer = region
    align.start = start
    align.end = end
    align.error = 0
    align.valid = True

    # Determine alignment sequences
    # Determine alignment sequences
    if not rev_primer:
        align.align_seq = str(seq_record.seq[:end])
        align.align_primer = '-' * start + region
    else:
        align.align_seq = str(seq_record.seq[start:])
        align.align_primer = region + '-' * (rec_len - end)

    return align


def maskSeq(align, mode='mask', barcode=False, barcode_length=None, barcode_field=default_barcode_field,
            primer_field=default_primer_field, delimiter=default_delimiter):
    """
    Create an output sequence with primers masked or cut

    Arguments:
      align : a PrimerAlignment object.
      mode : defines the action taken; one of 'cut', 'mask', 'tag' or 'trim'.
      barcode : if True add sequence preceding primer to description.
      barcode_length: length of barcode to extract. If None (default), use the whole sequence preceding the primer.
      barcode_field : name of the output barcode annotation.
      primer_field : name of the output primer annotation.
      delimiter : a tuple of delimiters for (annotations, field/values, value lists).

    Returns:
      Bio.SeqRecord.SeqRecord : masked sequence.
    """
    seq = align.seq

    # Build output sequence
    if mode == 'tag' or not align.align_primer:
        # Do not modify sequence
        out_seq = seq[:]
    elif mode == 'trim':
        # Remove region before primer
        if not align.rev_primer:
            out_seq = seq[align.start:]
        else:
            out_seq = seq[:align.end]
    elif mode == 'cut':
        # Remove primer and preceding region
        if not align.rev_primer:
            out_seq = seq[align.end:]
        else:
            out_seq = seq[:align.start]
    elif mode == 'mask':
        # Mask primer with Ns and remove preceding region
        if not align.rev_primer:
            mask_len = align.end - align.start + align.gaps
            out_seq = 'N' * mask_len + seq[align.end:]
            if hasattr(seq, 'letter_annotations') and \
                    'phred_quality' in seq.letter_annotations:
                out_seq.letter_annotations['phred_quality'] = \
                    [0] * mask_len + \
                    seq.letter_annotations['phred_quality'][align.end:]
        else:
            mask_len = min(align.end, len(seq)) - align.start + align.gaps
            out_seq = seq[:align.start] + 'N' * mask_len
            if hasattr(seq, 'letter_annotations') and \
                    'phred_quality' in seq.letter_annotations:
                out_seq.letter_annotations['phred_quality'] = \
                    seq.letter_annotations['phred_quality'][:align.start] + \
                    [0] * mask_len

    # Add alignment annotations to output SeqRecord
    out_seq.annotations = seq.annotations

    # Create output annotation
    out_ann = OrderedDict()
    if 'seqorient' in out_seq.annotations:
        out_ann['SEQORIENT'] = out_seq.annotations['seqorient']
    out_ann[primer_field] = align.primer

    # Add ID sequence to description
    if barcode:
        if barcode_length is None:
            # Extract all sequence preceding the primer
            seq_code = seq[:align.start].seq if not align.rev_primer \
                else seq[align.end:].seq
        else:
            # Extract sequence preceding the primer up to barcode_length
            seq_code = seq[(align.start - barcode_length):align.start].seq if not align.rev_primer \
                else seq[align.end:(align.end + barcode_length)].seq
        out_seq.annotations['barcode'] = seq_code
        out_ann[barcode_field] = seq_code

    seq_ann = parseAnnotation(seq.description, delimiter=delimiter)
    out_ann = mergeAnnotation(seq_ann, out_ann, delimiter=delimiter)
    out_seq.id = flattenAnnotation(out_ann, delimiter=delimiter)
    out_seq.description = ''

    return out_seq


def overlapConsensus(head_seq, tail_seq, ignore_chars=default_missing_chars):
    """
    Creates a consensus overlap sequences from two segments

    Arguments:
      head_seq : the overlap head SeqRecord.
      tail_seq : the overlap tail SeqRecord.
      ignore_chars : list of characters which do not contribute to consensus.

    Returns:
      SeqRecord: A SeqRecord object with consensus characters and quality scores.
    """
    # Initialize empty overlap character and quality score list
    seq_cons, score_cons = [], []
    # Define character and quality tuple iterators
    chars = list(zip(head_seq, tail_seq))
    quals = list(zip(head_seq.letter_annotations['phred_quality'],
                 tail_seq.letter_annotations['phred_quality']))

    # Iterate over character and quality tuples and build consensus
    for c, q in zip(chars, quals):
        # Equivalent character case
        if c[0] == c[1]:
            c_cons = c[0]
            q_cons = max(q)
        # All ambiguous characters case
        elif all([x in ignore_chars for x in c]):
            c_cons = 'N'
            q_cons = max(q)
        # Some ambiguous characters case
        elif any([x in ignore_chars for x in c]):
            c_cons = [x for x in c if x not in ignore_chars][0]
            q_cons = q[c.index(c_cons)]
        # Conflicting character case
        else:
            q_max = max(q)
            c_cons = c[q.index(q_max)]
            try:
                q_cons = int(q_max**2 / sum(q))
            except ZeroDivisionError:
                q_cons = 0
        # Append sequence and quality lists with consensus values
        seq_cons.append(c_cons)
        score_cons.append(q_cons)

    # Define overlap SeqRecord
    record = SeqRecord(Seq(''.join(seq_cons)),
                       id='',
                       name='',
                       description='',
                       letter_annotations={'phred_quality':score_cons})

    return record


def filterLength(data, min_length=default_filter_min_len, inner=True,
                 missing_chars=''.join(default_missing_chars)):
    """
    Filters sequences by length

    Arguments:
      data (SeqData): a SeqData object with a single SeqRecord to process.
      min_length (int): the minimum length allowed.
      inner (bool): if True exclude outer missing characters from calculation.
      missing_chars (str): a string of missing character values.

    Returns:
      SeqResult: SeqResult object.
    """
    # Get SeqRecord
    seq = data.data

    # Remove outer missing characters if required
    if inner:
        seq_str = str(seq.seq).strip(missing_chars)
        n = len(seq_str)
    else:
        n = len(seq)

    # Build result object
    valid = (n >= min_length)
    result = SeqResult(data.id, seq)
    if valid:
        result.results = seq
        result.valid = True

    # Update result log
    result.log['SEQ'] = seq.seq
    result.log['LENGTH'] = n

    return result


def filterMissing(data, max_missing=default_filter_max_missing, inner=True,
                  missing_chars=''.join(default_missing_chars)):
    """
    Filters sequences by number of missing nucleotides

    Arguments:
      data (SeqData): SeqData object with a single SeqRecord to process.
      max_missing (int): the maximum number of allowed ambiguous characters.
      inner (bool): if True exclude outer missing characters from calculation.
      missing_chars (str): a string of missing character values.

    Returns:
      SeqResult: SeqResult object.
    """
    # Get SeqRecord
    seq = data.data
    seq_str = str(seq.seq)

    # Remove outer missing character if required
    if inner:  seq_str = seq_str.strip(missing_chars)
    # Count missing characters
    n = len([c for c in seq_str if c in missing_chars])

    # Build result object
    valid = (n <= max_missing)
    result = SeqResult(data.id, seq)
    if valid:
        result.results = seq
        result.valid = True

    # Update result log
    result.log['SEQ'] = seq.seq
    result.log['MISSING'] = n

    return result


def filterRepeats(data, max_repeat=default_filter_max_repeat, include_missing=False, inner=True,
                  missing_chars=''.join(default_missing_chars)):
    """
    Filters sequences by fraction of ambiguous nucleotides

    Arguments:
      data (SeqData): a SeqData object with a single SeqRecord to process.
      max_repeat (int): the maximum number of allowed repeating characters.
      include_missing (int): if True count ambiguous character repeats;
                             if False do not consider ambiguous character repeats.
      inner (int): if True exclude outer missing characters from calculation.
      missing_chars (str): a string of missing character values.

    Returns:
      SeqResult: SeqResult object.
    """
    # Get SeqRecord
    seq = data.data
    seq_str = str(seq.seq)

    # Remove outer missing character if required
    if inner:  seq_str = seq_str.strip(missing_chars)
    # Remove missing characters if required
    if not include_missing:
        seq_str = ''.join([c for c in seq_str if c not in missing_chars])

    groups = ((c, len(list(g))) for c, g in groupby(seq_str))
    __, n = max(groups, key=lambda x: x[1])

    # Build result object
    valid = (n <= max_repeat)
    result = SeqResult(data.id, seq)
    if valid:
        result.results = seq
        result.valid = True

    # Update result log
    result.log['SEQ'] = seq.seq
    result.log['REPEATS'] = n

    return result

def meanQuality(qual):
    """
    Calculate mean of quality scores.
    Note: this is desired over mean of probabilities as the mean of probabilities gives higher weight to bad quality scores.

    Arguments:
      qual (list): numeric Phred quality scores.

    Returns:
      int: floor of the mean Phred quality score.
    """
    # Assign 0 to empty list
    if len(qual) == 0:
        return 0

    qual_sum = 0.0
    for q in qual:  qual_sum += q

    return math.floor(qual_sum / len(qual))


def filterQuality(data, min_qual=default_consensus_min_qual, inner=True,
                  missing_chars=''.join(default_missing_chars)):
    """
    Filters sequences by quality score

    Arguments:
      data (SeqData): a SeqData object with a single SeqRecord to process.
      min_qual (int): minimum mean quality score for retained sequences.
      inner (bool): if True exclude outer missing characters from calculation.
      missing_chars (str): a string of missing character values.

    Returns:
      SeqResult: SeqResult object.
    """
    # Get SeqRecord
    seq = data.data

    if inner:
        seq_str = str(seq.seq)
        seq_cut = seq_str.strip(missing_chars)
        s = seq_str.find(seq_cut)
        quals =  seq.letter_annotations['phred_quality'][s:s + len(seq_cut)]
    else:
        quals = seq.letter_annotations['phred_quality']

    # Calculate mean quality
    mean_qual = meanQuality(quals)

    # Build result object
    valid = (mean_qual >= min_qual)
    result = SeqResult(data.id, seq)
    if valid:
        result.results = seq
        result.valid = True

    # Update result log
    result.log['SEQ'] = seq.seq
    result.log['QUALITY'] = mean_qual

    return result


def trimQuality(data, min_qual=default_consensus_min_qual, window=default_filter_window, reverse=False):
    """
    Cuts sequences using a moving mean quality score

    Arguments:
      data (SeqData): a SeqData object with a single SeqRecord to process.
      min_qual (int): minimum mean quality to define a cut point.
      window (int): nucleotide window size.
      reverse (bool): if True cut the head of the sequence;
                      if False cut the tail of the sequence

    Returns:
      SeqResult: SeqResult object.
    """
    # Get SeqRecord
    seq = data.data

    quals = seq.letter_annotations['phred_quality']
    # Reverse quality scores if required
    if reverse:  quals = quals[::-1]

    # Scan across quality scores for first quality drop-off
    end = len(quals)
    for s in range(0, end, window):
        q_win = quals[s:s + window]
        q = sum(q_win) / len(q_win)
        if q < min_qual:
            end = s
            break

    # Define trimmed sequence
    if not reverse:
        trim_seq = seq[:end]
        out_str = str(trim_seq.seq)
    else:
        trim_seq = seq[len(seq) - end:]
        out_str =  ' ' * (len(seq) - end) + str(trim_seq.seq)

    # Build result object
    valid = (len(trim_seq) > 0)
    result = SeqResult(data.id, seq)
    if valid:
        result.results = trim_seq
        result.valid = True

    # Update result log
    result.log['INSEQ'] = seq.seq
    result.log['OUTSEQ'] = out_str
    result.log['LENGTH'] = len(trim_seq)

    return result


def maskQuality(data, min_qual=default_consensus_min_qual):
    """
    Masks characters by in sequence by quality score

    Arguments:
      data (SeqData): a SeqData object with a single SeqRecord to process.
      min_qual (int): minimum quality for retained characters.

    Returns:
      SeqResult: SeqResult object.
    """
    # Get SeqRecord
    seq = data.data
    seq_str = str(seq.seq)
    quals = seq.letter_annotations['phred_quality']

    # Mask low quality nucleotides
    mask_chars = [seq_str[i] if q >= min_qual else 'N' for i, q in enumerate(quals)]
    mask_count = sum(1 for q in quals if q < min_qual)

    # Define masked SeqRecord
    mask_seq = SeqRecord(Seq(''.join(mask_chars)),
                         id=seq.id,
                         name=seq.name,
                         description=seq.description,
                         letter_annotations=seq.letter_annotations)

    # Build result object
    result = SeqResult(data.id, seq)
    result.results = mask_seq
    result.valid = True

    # Update result log
    result.log['INSEQ'] = seq.seq
    result.log['OUTSEQ'] = mask_seq.seq
    result.log['MASKED'] = mask_count

    return result


def referenceAssembly(head_seq, tail_seq, ref_dict, ref_db, min_ident=default_assembly_min_ident,
                      evalue=default_assembly_evalue, max_hits=default_assembly_max_hits, fill=False,
                      aligner='usearch', aligner_exec=default_usearch_exec,
                      score_dict=getDNAScoreDict(mask_score=(1, 1), gap_score=(0, 0))):
    """
    Stitches two sequences together by aligning against a reference database

    Arguments:
      head_seq : the head SeqRecord.
      head_seq : the tail SeqRecord.
      ref_dict : a dictionary of reference SeqRecord objects.
      ref_db : the path and name of the reference database.
      min_ident : the minimum identity for a valid assembly.
      evalue : the E-value cut-off for ublast.
      max_hits : the maxhits output limit for ublast.
      fill : if False non-overlapping regions will be assigned Ns;
             if True non-overlapping regions will be filled with the reference sequence.
      aligner : the alignment tool; one of 'blastn' or 'usearch'.
      aligner_exec : the path to the alignment tool executable.
      score_dict : optional dictionary of character scores in the
                   form {(char1, char2): score}.

    Returns:
      AssemblyRecord: assembled sequence object.
    """
    try:
        align_func = {'blastn': runBlastn, 'usearch': runUBlast}[aligner]
    except:
        printError('Invalid alignment tool %s.' % aligner)

    # Define general parameters
    head_len = len(head_seq)
    tail_len = len(tail_seq)

    # Determine if quality scores are present
    has_quality = hasattr(head_seq, 'letter_annotations') and \
                  hasattr(tail_seq, 'letter_annotations') and \
                  'phred_quality' in head_seq.letter_annotations and \
                  'phred_quality' in tail_seq.letter_annotations

    # Align against reference
    head_df = align_func(head_seq, database=ref_db, evalue=evalue, max_hits=max_hits,
                         aligner_exec=aligner_exec)
    tail_df = align_func(tail_seq, database=ref_db, evalue=evalue, max_hits=max_hits,
                         aligner_exec=aligner_exec)

    # Subset results to matching reference assignments
    align_df = pd.merge(head_df, tail_df, on='target', how='inner', suffixes=('_head', '_tail'))

    # If no matching targets return failed results
    if len(align_df) < 1:
        return AssemblyRecord()

    # Select top alignment
    align_top = align_df.iloc[0, :]
    ref_id = align_top['target']
    ref_seq = ref_dict[ref_id]

    # Get offset of target and reference positions
    head_shift = align_top['target_start_head'] - align_top['query_start_head']
    tail_shift = align_top['target_start_tail'] - align_top['query_start_tail']

    # Get positions of outer reference match in head (a, b) and tail (x, y) sequences
    outer_start = align_top[['target_start_head', 'target_start_tail']].min()
    outer_end = align_top[['target_end_head', 'target_end_tail']].max()
    a_outer = outer_start - head_shift
    b_outer = outer_end - head_shift
    x_outer = outer_start - tail_shift
    y_outer = outer_end - tail_shift

    # Get positions of inner reference match in head (a,b) and tail (x,y) sequences
    inner_start = align_top[['target_start_head', 'target_start_tail']].max()
    inner_end = align_top[['target_end_head', 'target_end_tail']].min()
    a_inner = inner_start - head_shift
    b_inner = inner_end - head_shift
    x_inner = inner_start - tail_shift
    y_inner = inner_end - tail_shift

    # Determine head (a, b) and tail (x, y) overlap positions
    a = max(0, a_inner - x_inner)
    b = min(b_inner + (tail_len - y_inner), head_len)
    x = max(0, x_inner - a_inner)
    y = min(y_inner + (head_len - b_inner), tail_len)

    # Join sequences if head and tail do not overlap, otherwise assemble
    if a > b and x > y:
        stitch = joinAssembly(head_seq, tail_seq, gap=(a - b), insert_seq=None)
    else:
        stitch = AssemblyRecord()
        stitch.gap = 0

        # Define overlap sequence
        if has_quality:
            # Build quality consensus
            overlap_seq = overlapConsensus(head_seq[a:b], tail_seq[x:y])
        else:
            # Assign head sequence to conflicts when no quality information is available
            overlap_seq = head_seq[a:b]

        # Assemble sequence
        if a > 0 and y < tail_len:
            # Tail overlaps end of head
            stitch.seq = head_seq[:a] + overlap_seq + tail_seq[y:]
        elif b < head_len and x > 0:
            # Head overlaps end of tail
            stitch.seq = tail_seq[:x] + overlap_seq + head_seq[b:]
        elif a == 0 and b == head_len:
            # Head is a subsequence of tail
            stitch.seq = tail_seq[:x] + overlap_seq + tail_seq[y:]
        elif x == 0 and y == tail_len:
            # Tail is a subsequence of head
            stitch.seq = head_seq[:a] + overlap_seq + head_seq[b:]
        else:
            printWarning('Invalid overlap condition for %s' % head_seq.id)

        # Define stitch ID
        stitch.seq.id = head_seq.id if head_seq.id == tail_seq.id \
                                    else '+'.join([head_seq.id, tail_seq.id])
        stitch.seq.name = stitch.seq.id
        stitch.seq.description = ''

    # Assign position info
    stitch.head_pos = (a, b)
    stitch.tail_pos = (x, y)

    # Assign reference info
    stitch.ref_seq = ref_seq[outer_start:outer_end]
    stitch.ref_pos = (max(a_outer, x_outer), max(b_outer, y_outer))
    stitch.evalue = tuple(align_top[['evalue_head', 'evalue_tail']])

    # Calculate assembly error
    score, weight, error = scoreSeqPair(stitch.seq.seq[stitch.ref_pos[0]:stitch.ref_pos[1]],
                                        ref_seq.seq[outer_start:outer_end],
                                        score_dict=score_dict)
    stitch.ident = 1 - error
    stitch.valid = bool(stitch.ident >= min_ident)

    # Fill gap with reference if required
    if a > b and x > y and fill:
        insert_seq = ref_seq.seq[(b + head_shift):(a + head_shift)]
        insert_rec = joinAssembly(head_seq, tail_seq, gap=(a - b), insert_seq=insert_seq)
        stitch.seq = insert_rec.seq

    return stitch


def joinAssembly(head_seq, tail_seq, gap=default_assembly_gap, insert_seq=None):
    """
    Concatenates two sequences

    Arguments:
      head_seq : the head SeqRecord.
      tail_seq : the tail SeqRecord.
      gap : number of gap characters to insert between head and tail
            ignored if insert_seq is not None.
      insert_seq : a string or Bio.Seq.Seq object, to insert between the head and tail;
                 if None insert with N characters.

    Returns:
      AssemblyRecord: assembled sequence object.
    """
    # Define joined ID
    join_id = head_seq.id if head_seq.id == tail_seq.id \
              else '+'.join([head_seq.id, tail_seq.id])

    # Join sequences
    if insert_seq is None:
        join_seq = str(head_seq.seq) + 'N' * gap + str(tail_seq.seq)
    else:
        gap = len(insert_seq)
        join_seq = str(head_seq.seq) + str(insert_seq) + str(tail_seq.seq)

    # Define return record
    record = SeqRecord(Seq(join_seq),
                       id=join_id,
                       name=join_id,
                       description='')

    # Join quality score if present
    has_quality = hasattr(head_seq, 'letter_annotations') and \
                  hasattr(tail_seq, 'letter_annotations') and \
                  'phred_quality' in head_seq.letter_annotations and \
                  'phred_quality' in tail_seq.letter_annotations
    if has_quality:
        join_quality = head_seq.letter_annotations['phred_quality'] + \
                       [0] * gap + \
                       tail_seq.letter_annotations['phred_quality']
        record.letter_annotations = {'phred_quality':join_quality}

    stitch = AssemblyRecord(record)
    stitch.valid = True
    stitch.gap = gap

    return stitch


def alignAssembly(head_seq, tail_seq, alpha=default_assembly_alpha, max_error=default_assembly_max_error,
                  min_len=default_assembly_min_len, max_len=default_assembly_max_len, scan_reverse=False,
                  assembly_stats=None, score_dict=getDNAScoreDict(mask_score=(1, 1), gap_score=(0, 0))):
    """
    Stitches two sequences together by aligning the ends

    Arguments:
      head_seq : the head SeqRecord.
      head_seq : the tail SeqRecord.
      alpha : the minimum p-value for a valid assembly.
      max_error : the maximum error rate for a valid assembly.
      min_len : minimum length of overlap to test.
      max_len : maximum length of overlap to test.
      scan_reverse : if True allow the head sequence to overhang the end of the tail sequence
                     if False end alignment scan at end of tail sequence or start of head sequence.
      assembly_stats : optional successes by trials numpy.array of p-values.
      score_dict : optional dictionary of character scores in the .
                   form {(char1, char2): score}.

    Returns:
      AssemblyRecord: assembled sequence object.
    """
    # Define general parameters
    stitch = AssemblyRecord()
    if assembly_stats is None:  assembly_stats = AssemblyStats(max_len + 1)
    head_str = str(head_seq.seq)
    tail_str = str(tail_seq.seq)
    head_len = len(head_str)
    tail_len = len(tail_str)

    # Fail if sequences are too short
    if head_len <= min_len or tail_len <= min_len:
        return stitch

    # Determine if quality scores are present
    has_quality = hasattr(head_seq, 'letter_annotations') and \
                  hasattr(tail_seq, 'letter_annotations') and \
                  'phred_quality' in head_seq.letter_annotations and \
                  'phred_quality' in tail_seq.letter_annotations

    # Determine if sub-sequences are allowed and define scan range
    if scan_reverse and max_len >= min(head_len, tail_len):
        scan_len = head_len + tail_len - min_len
    else:
        scan_len = min(max(head_len, tail_len), max_len)

    # Iterate and score overlap segments
    for i in range(min_len, scan_len + 1):
        a = max(0, head_len - i)
        b = head_len - max(0, i - tail_len)
        x = max(0, i - head_len)
        y = min(tail_len, i)
        score, weight, error = scoreSeqPair(head_str[a:b], tail_str[x:y], score_dict=score_dict)
        z = assembly_stats.z[score, weight]
        # Save stitch as optimal if z-score improves
        if z > stitch.zscore:
           stitch.head_pos = (a, b)
           stitch.tail_pos = (x, y)
           stitch.zscore = z
           stitch.pvalue = assembly_stats.p[score, weight]
           stitch.error = error

    # Build stitched sequences and assign best_dict values
    if stitch.head_pos is not None:
        # Correct quality scores and resolve conflicts
        a, b = stitch.head_pos
        x, y = stitch.tail_pos
        if has_quality:
            # Build quality consensus
            overlap_seq = overlapConsensus(head_seq[a:b], tail_seq[x:y])
        else:
            # Assign head sequence to conflicts when no quality information is available
            overlap_seq = head_seq[a:b]

        if a > 0 and y < tail_len:
            # Tail overlaps end of head
            stitch.seq = head_seq[:a] + overlap_seq + tail_seq[y:]
        elif b < head_len and x > 0:
            # Head overlaps end of tail
            stitch.seq = tail_seq[:x] + overlap_seq + head_seq[b:]
        elif a == 0 and b == head_len:
            # Head is a subsequence of tail
            stitch.seq = tail_seq[:x] + overlap_seq + tail_seq[y:]
        elif x == 0 and y == tail_len:
            # Tail is a subsequence of head
            stitch.seq = head_seq[:a] + overlap_seq + head_seq[b:]
        else:
            printWarning('Invalid overlap condition for %s.' % head_seq.id)


        # Define best stitch ID
        stitch.seq.id = head_seq.id if head_seq.id == tail_seq.id \
                              else '+'.join([head_seq.id, tail_seq.id])
        stitch.seq.name = stitch.seq.id
        stitch.seq.description = ''

    stitch.valid = bool(stitch.pvalue <= alpha and stitch.error <= max_error)

    return stitch


def sequentialAssembly(head_seq, tail_seq, ref_dict, ref_db,
                       alpha=default_assembly_alpha, max_error=default_assembly_max_error,
                       min_len=default_assembly_min_len, max_len=default_assembly_max_len, scan_reverse=False,
                       min_ident=default_assembly_min_ident, evalue=default_assembly_evalue, max_hits=default_assembly_max_hits,
                       fill=False, aligner='usearch', aligner_exec=default_usearch_exec,
                       assembly_stats=None, score_dict=getDNAScoreDict(mask_score=(1, 1), gap_score=(0, 0))):
    """
    Stitches sequences together by first attempting de novo assembly then falling back to reference guided assembly

    Arguments:
      head_seq : the head SeqRecord
      head_seq : the tail SeqRecord
      ref_dict : a dictionary of reference SeqRecord objects
      ref_db : the path and name of the reference database
      alpha : the minimum p-value for a valid de novo assembly
      max_error : the maximum error rate for a valid de novo assembly
      min_len : minimum length of overlap to test for de novo assembly
      max_len : maximum length of overlap to test for de novo assembly
      scan_reverse : if True allow the head sequence to overhang the end of the tail sequence in de novo assembly
                     if False end alignment scan at end of tail sequence or start of head sequence
      min_ident : the minimum identity for a valid reference guided assembly
      evalue : the E-value cut-off for reference guided assembly
      max_hits : the maxhits output limit for reference guided assembly
      fill : if False non-overlapping regions will be assigned Ns in reference guided assembly;
             if True non-overlapping regions will be filled with the reference sequence.
      aligner : the alignment tool; one of 'blastn' or 'usearch'
      aligner_exec : the path to the alignment tool executable
      assembly_stats : optional successes by trials numpy.array of p-values
      score_dict : optional dictionary of character scores in the
                   form {(char1, char2): score}.

    Returns:
      AssemblyRecord: assembled sequence object.
    """
    # First attempt align mode
    stitch = alignAssembly(head_seq, tail_seq, alpha=alpha, max_error=max_error,
                  min_len=min_len, max_len=max_len, scan_reverse=scan_reverse,
                  assembly_stats=assembly_stats, score_dict=score_dict)

    # Then try reference mode
    if not stitch:
        stitch = referenceAssembly(head_seq, tail_seq, ref_dict, ref_db, min_ident=min_ident,
                                   evalue=evalue, max_hits=max_hits, fill=fill,
                                   aligner=aligner, aligner_exec=aligner_exec,
                                   score_dict=score_dict)

    return stitch


def consensusUnify(data, field, delimiter=default_delimiter):
    """
    Reassigns all annotations to the consensus annotation in group

    Arguments:
      data : SeqData object contain sequences to process.
      field : field containing annotations to collapse.
      delimiter : a tuple of delimiters for (annotations, field/values, value lists).

    Returns:
      SeqResult: modified sequences.
    """
    # Copy data into new object
    records = deepcopy(data.data)

    # Define result object
    result = SeqResult(data.id, data.data)
    result.log['SEQCOUNT'] = len(data)
    #for i, seq in enumerate(records, start=1):
    #    header = parseAnnotation(seq.description, delimiter=delimiter)
    #    result.log['%s-%i' % (field, i)] = header[field]

    # Get consensus annotation
    cons_dict = annotationConsensus(records, field)
    result.log['VALCOUNT'] = len(cons_dict['set'])
    result.log['VALUES'] = ','.join(cons_dict['set'])
    result.log['COUNTS'] = ','.join((str(x) for x in cons_dict['count']))
    result.log['CONSFREQ'] = cons_dict['freq']
    result.log['CONSENSUS'] = cons_dict['cons']

    if cons_dict['freq'] != 1:
        # Update sequence annotations with consensus annotation
        for i, seq in enumerate(records):
            header = parseAnnotation(seq.description, delimiter=delimiter)
            header[field] = cons_dict['cons']
            seq.id = seq.name = flattenAnnotation(header, delimiter=delimiter)
            seq.description = ''

    # Check results
    result.results = records
    result.valid = True

    return result


def deletionUnify(data, field, delimiter=default_delimiter):
    """
    Removes all sequences with differing annotations in a group

    Arguments:
      data : SeqData object contain sequences to process.
      field : field containing annotations to collapse.
      delimiter : a tuple of delimiters for (annotations, field/values, value lists).

    Returns:
      SeqResult: modified sequences.
    """
    # Set reference to data
    records = data.data

    # Define result object
    result = SeqResult(data.id, data.data)
    result.log['SEQCOUNT'] = len(data)
    # for i, seq in enumerate(records, start=1):
    #     header = parseAnnotation(seq.description, delimiter=delimiter)
    #     result.log['%s-%i' % (field, i)] = header[field]

    # I the number of unique identities in the annotation field is not 1, then the group is invalid and should be removed
    value_set = sorted(set(parseAnnotation(seq.description, delimiter=delimiter)[field] for seq in records))
    if len(value_set) == 1:
        result.valid = True
    else:
        result.valid = False
    result.results = records

    # Update log
    result.log['VALCOUNT'] = len(value_set)
    result.log['VALUES'] = ','.join(value_set)
    result.log['RETAIN'] = result.valid

    return result
