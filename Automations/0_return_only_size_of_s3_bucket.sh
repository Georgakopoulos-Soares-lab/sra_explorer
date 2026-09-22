aws s3 ls s3://sra-pub-metadata-us-east-1/sra/metadata/ \
  --recursive \
  --no-sign-request \
  > sra_metadata_filelist.txt

awk '{sum += $3} END {print sum/1024/1024/1024 " GB"}' sra_metadata_filelist.txt

wc -l sra_metadata_filelist.txt


