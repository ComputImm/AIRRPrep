"""
Default parameters
"""
# Info
__author__ = 'Jason Anthony Vander Heiden, Namita Gupta'

# Annotation parameters
default_delimiter = ('|', '=', ',')
default_separator = default_delimiter[2]

# Commandline argument defaults
choices_coord = ['illumina', 'solexa', 'sra', '454', 'presto']
default_coord = 'presto'
default_out_args = {'log_file':None,
                    'delimiter':default_delimiter,
                    'separator':default_separator,
                    'out_dir':None,
                    'out_name':None,
                    'out_type':None,
                    'failed':True}

# Fields
default_barcode_field = 'BARCODE'
default_primer_field = 'PRIMER'
default_cluster_field = 'CLUSTER'

# External applications
default_muscle_exec = 'muscle'
default_usearch_exec = 'usearch'
default_vsearch_exec = 'vsearch'
default_cdhit_exec = 'cd-hit-est'
default_blastn_exec = 'blastn'
default_blastdb_exec = 'makeblastdb'

# Sequence sets
default_gap_chars = set(['-', '.'])
default_mask_chars = set(['n', 'N'])
default_missing_chars = set(['-', '.', 'n', 'N'])
default_missing_residues = set(['.', '-', 'x', 'N'])

# Consensus defaults
default_consensus_min_freq = 0.6
default_consensus_min_qual = 0

# Primer defaults
default_primer_gap_penalty = (1, 1)
default_primer_max_error = 0.2
default_primer_max_len = 50
default_primer_start = 0

# Filter defaults
default_filter_min_qual = 20
default_filter_max_missing = 10
default_filter_max_repeat = 15
default_filter_min_len = 250
default_filter_window = 10

# Assembly defaults
default_assembly_alpha = 1e-5
default_assembly_max_error = 0.3
default_assembly_min_ident = 0.5
default_assembly_min_len = 8
default_assembly_max_len = 1000
default_assembly_gap = 0
default_assembly_evalue = 1e-5
default_assembly_max_hits = 100
default_consensus_min_count = 1