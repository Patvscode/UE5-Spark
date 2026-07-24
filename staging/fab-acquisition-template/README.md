# Fab acquisition staging

This is a disposable, content-only Unreal project. It enables Epic's Fab
Editor plugin without enabling Fab in the sealed Fay runtime project.

Licensed downloads, generated project data, authentication state, logs, and
imported content stay in the private Spark workspace. Do not copy them into
this source template or publish them.

Use only the guarded `prepare-fex-fab-staging.sh`,
`build-fex-fab-staging.sh`, and `run-fex-fab-staging.sh` wrappers. The launch
wrapper requires a reviewed non-content baseline and verifies it again after
the Editor exits.
