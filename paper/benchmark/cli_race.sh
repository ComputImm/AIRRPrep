#!/usr/bin/env bash
# CLI-pRESTO: UMI-barcoded Illumina MiSeq 325+275 paired-end 5'RACE BCR mRNA
# (VanderHeiden2017). One OS process per operation, exactly as the reference
# shell script distributed with pRESTO does it.
set -e
PY="$1"      # interpreter to use (same venv python as the backend)
S="$2"       # directory holding the pRESTO console scripts
$PY "$S/FilterSeq.py" quality -s SRR4026043_1.fastq -q 20 --outname HD09N-R1 --log FS1.log
$PY "$S/FilterSeq.py" quality -s SRR4026043_2.fastq -q 20 --outname HD09N-R2 --log FS2.log
$PY "$S/MaskPrimers.py" score -s HD09N-R1_quality-pass.fastq -p AbSeq_R1_Human_IG_Primers.fasta --start 0 --mode cut --outname HD09N-R1 --log MP1.log
$PY "$S/MaskPrimers.py" score -s HD09N-R2_quality-pass.fastq -p AbSeq_R2_TS.fasta --start 17 --barcode --mode cut --maxerror 0.5 --outname HD09N-R2 --log MP2.log
$PY "$S/PairSeq.py" -1 HD09N-R1_primers-pass.fastq -2 HD09N-R2_primers-pass.fastq --2f BARCODE --coord sra
$PY "$S/BuildConsensus.py" -s HD09N-R1_primers-pass_pair-pass.fastq --bf BARCODE --pf PRIMER --prcons 0.6 --maxerror 0.1 --maxgap 0.5 --outname HD09N-R1 --log BC1.log
$PY "$S/BuildConsensus.py" -s HD09N-R2_primers-pass_pair-pass.fastq --bf BARCODE --maxerror 0.1 --maxgap 0.5 --outname HD09N-R2 --log BC2.log
$PY "$S/PairSeq.py" -1 HD09N-R1_consensus-pass.fastq -2 HD09N-R2_consensus-pass.fastq --coord presto
$PY "$S/AssemblePairs.py" sequential -1 HD09N-R2_consensus-pass_pair-pass.fastq -2 HD09N-R1_consensus-pass_pair-pass.fastq -r IMGT_Human_IG_V.fasta --coord presto --rc tail --scanrev --1f CONSCOUNT --2f CONSCOUNT PRCONS --aligner blastn --outname HD09N-C --log AP.log
$PY "$S/MaskPrimers.py" align -s HD09N-C_assemble-pass.fastq -p AbSeq_Human_IG_InternalCRegion.fasta --maxlen 100 --maxerror 0.3 --mode tag --revpr --skiprc --pf CREGION --outname HD09N-C --log MP3.log
$PY "$S/ParseHeaders.py" collapse -s HD09N-C_primers-pass.fastq -f CONSCOUNT --act min
$PY "$S/CollapseSeq.py" -s HD09N-C_primers-pass_reheader.fastq -n 20 --inner --uf CREGION --cf CONSCOUNT --act sum --outname HD09N-C
$PY "$S/SplitSeq.py" group -s HD09N-C_collapse-unique.fastq -f CONSCOUNT --num 2 --outname HD09N-C
$PY "$S/ParseHeaders.py" table -s HD09N-C_atleast-2.fastq -f ID CREGION CONSCOUNT DUPCOUNT
