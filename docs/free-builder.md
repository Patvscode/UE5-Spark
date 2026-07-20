# Free temporary x86-64 builder

An adequate forever-free x86-64 VM is not normally available for this workload.
The practical $0 route is new-user cloud credit, if eligible.

## Recommended trial configuration

Google Cloud currently offers eligible new users $300 of credit for 90 days and
states that a Free Trial account is not automatically billed or upgraded. Check
the current [Free Program terms](https://docs.cloud.google.com/free/docs/free-cloud-features)
and [signup FAQ](https://cloud.google.com/signup-faqs) before creating anything.

A reasonable CPU-only builder is:

| Resource | Starting point |
|---|---|
| OS/architecture | Ubuntu 22.04 x86-64 |
| Machine | `e2-highmem-8` or comparable |
| CPU/RAM | 8 vCPU / 64 GiB |
| Disk | 500 GiB balanced persistent disk |
| GPU | None for headless cooking |

At prices checked on 2026-07-20, the `e2-highmem-8` compute plus a continuously
allocated 500-GiB balanced disk was approximately $0.43/hour before discounts.
A 24–72 hour build would use roughly $10–$31 of trial credit. Network egress,
snapshots, taxes, and other services are additional. Cloud prices, quotas, and
eligibility can change; verify the estimate using Google's
[VM pricing](https://cloud.google.com/products/compute/pricing/general-purpose)
and [disk pricing](https://cloud.google.com/compute/disks-image-pricing).

## Cost-safety rules

1. Select the Free Trial account and do not manually upgrade it to paid billing.
2. Use CPU only; a GPU is unnecessary for the headless cook milestone.
3. Set a budget alert even though a trial account should not auto-bill.
4. Stop the VM whenever no build is running.
5. Download the verified ARM64 package before deleting resources.
6. Delete the VM and its persistent disk immediately after the package is safe.

## No-card alternative

Eligible students can check
[Azure for Students](https://azure.microsoft.com/en-us/free/students), which
currently advertises credit without requiring a credit card. Its credit and VM
quota still need to support at least a 32 GB, preferably 64 GB, x86-64 builder.

## Local emulation fallback

FEX can run some x86-64 Linux applications on ARM64 in a user-owned workspace,
but a full Unreal cook launches many CPU-heavy helper processes and performs
large filesystem workloads. Treat it only as a bounded experiment, not as the
reliable build route.
