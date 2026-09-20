#!/usr/bin/env bash
# CLI-pRESTO: UMI-barcoded Illumina MiSeq 2x250 paired-end BCR mRNA (Stern2014).
set -e
PY="$1"
S="$2"
$PY "$S/FilterSeq.py" quality -s SRR1383456_1.fastq -q 20 --outname MS12_R1 --log FS1.log
$PY "$S/FilterSeq.py" quality -s SRR1383456_2.fastq -q 20 --outname MS12_R2 --log FS2.log
$PY "$S/MaskPrimers.py" score -s MS12_R1_quality-pass.fastq -p Stern2014_CPrimers.fasta --start 15 --mode cut --barcode --outname MS12_R1 --log MP1.log
$PY "$S/MaskPrimers.py" score -s MS12_R2_quality-pass.fastq -p Stern2014_VPrimers.fasta --start 0 --mode mask --outname MS12_R2 --log MP2.log
$PY "$S/PairSeq.py" -1 MS12_R1_primers-pass.fastq -2 MS12_R2_primers-pass.fastq --1f BARCODE --coord sra
$PY "$S/BuildConsensus.py" -s MS12_R1_primers-pass_pair-pass.fastq --bf BARCODE --pf PRIMER --prcons 0.6 --maxerror 0.1 --maxgap 0.5 --outname MS12_R1 --log BC1.log
$PY "$S/BuildConsensus.py" -s MS12_R2_primers-pass_pair-pass.fastq --bf BARCODE --maxerror 0.1 --maxgap 0.5 --outname MS12_R2 --log BC2.log
$PY "$S/PairSeq.py" -1 MS12_R1_consensus-pass.fastq -2 MS12_R2_consensus-pass.fastq --coord presto
$PY "$S/AssemblePairs.py" align -1 MS12_R2_consensus-pass_pair-pass.fastq -2 MS12_R1_consensus-pass_pair-pass.fastq --coord presto --rc tail --1f CONSCOUNT --2f CONSCOUNT PRCONS --outname MS12 --log AP.log
$PY "$S/ParseHeaders.py" collapse -s MS12_assemble-pass.fastq -f CONSCOUNT --act min
$PY "$S/CollapseSeq.py" -s MS12_assemble-pass_reheader.fastq -n 20 --inner --uf PRCONS --cf CONSCOUNT --act sum --outname MS12
$PY "$S/SplitSeq.py" group -s MS12_collapse-unique.fastq -f CONSCOUNT --num 2 --outname MS12
$PY "$S/ParseHeaders.py" table -s MS12_atleast-2.fastq -f ID PRCONS CONSCOUNT DUPCOUNT
