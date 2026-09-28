# Tool versions in the AIRRPrep backend image

Image tag: `ghcr.io/computimm/airrprep-backend:v1.0.0`
AIRRPrep version: `v1.0.0` (commit `9148dba8bdd4c516b80db4eece07dd0a0b23a929`)
Local image id: `sha256:1cc4dcc98bb2869f9b6d6300887f6d593e1ba2e2464ae1e864113a62a6da4e96`
Size: 1031887925 bytes
Registry digest: `ghcr.io/computimm/airrprep-backend@sha256:1cc4dcc98bb2869f9b6d6300887f6d593e1ba2e2464ae1e864113a62a6da4e96`
Platform: linux/amd64

Pull exactly this image with

```bash
docker pull ghcr.io/computimm/airrprep-backend@sha256:1cc4dcc98bb2869f9b6d6300887f6d593e1ba2e2464ae1e864113a62a6da4e96
```

Read the same manifest back out of any image with

```bash
docker run --rm --entrypoint cat ghcr.io/computimm/airrprep-backend:v1.0.0 /app/TOOL_VERSIONS.txt
```

```
# Tool versions resolved when this image was built
# base image: python:3.12-slim
build_date=2026-09-28T10:14:27Z
debian=13.7
python=3.12.14
samtools=1.21-1
ncbi-blast+=2.16.0+ds-7
muscle3=3.8.1551-3
vsearch=2.30.0-1
cd-hit=4.8.1-4
perl=5.40.1-6+deb13u1
zlib1g=1:1.3.dfsg+really1.3.1-1+b1
libpq5=17.11-0+deb13u1
trust4=1.1.9
usearch=not included (proprietary; set USEARCH_BIN to your own binary)
```
