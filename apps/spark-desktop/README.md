# DGX Spark desktop applications

These launchers expose only the useful graphical entry points in this project:

- **UE5 Spark Avatar** starts the private companion controller and opens it in
  Chromium app mode.
- **NVIDIA ARDY Character Lab** starts the project overlay around NVIDIA's real
  ARDY Viser demo and opens it in Chromium app mode.
- **ARDY Blender** is installed by `scripts/install-ardy-blender.sh` and remains
  the primary character-rigging application.
- **Unreal Editor 5.8 (Experimental)** launches the real x86-64 UE 5.8 Editor
  through the reviewed FEX/Vulkan adapter. It is explicitly labeled
  experimental because startup is slow and Linux ARM64 is not Epic's normal
  Editor-host workflow.

The installer deliberately does not add icons for the superseded custom Rig
Lab, raw duplicate ARDY demos, backend services, renderer supervisors, tests,
or authentication utilities.

Install or refresh the desktop and application-menu entries on the Spark:

```bash
./scripts/install-spark-desktop-launchers.sh
```

Web launchers start their fixed user service, wait for its loopback endpoint,
and only then open the tailnet HTTPS application. They accept no arbitrary
service names or URLs.
