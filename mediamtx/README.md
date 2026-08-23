# MediaMTX gateway

MediaMTX is the optional ingress and HLS gateway for paths selected in the
private Nginx render profile and in `node.env`.

- legacy Nginx RTMP remains on TCP 1935;
- MediaMTX RTMP uses TCP 19350;
- MediaMTX SRT uses UDP 8890;
- HLS, API and metrics listen on loopback only;
- a path accepts RTMP or SRT, but never two publishers simultaneously.

`mediamtx.yml.example` contains no production secret. For a new node, copy it
to `/etc/mediamtx/mediamtx.yml`, replace the `CHANGE_ME` password, set
ownership to `root:mediamtx` and mode 0640, then validate before starting the
service.

The general project updater installs the packaged systemd unit but deliberately
does not copy or replace the live MediaMTX configuration and does not restart
MediaMTX. This prevents an application-only update from interrupting publishers.

Initial migration policy:

1. keep places 1-8 on Nginx RTMP and file-backed HLS;
2. prepare MediaMTX paths 1-16 and authenticated RTMP/SRT publishing;
3. move one place at a time;
4. add a migrated place to both `mediamtx_hls_places` in the Nginx render
   profile and `ARENA_RTMP_MEDIAMTX_HLS_PLACES` in `node.env`;
5. retain the old RTMP worker until the SRT path, HLS and monitoring are checked.
