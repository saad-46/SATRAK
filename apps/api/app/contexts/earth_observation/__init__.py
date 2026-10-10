"""Earth Observation bounded context — the reusable satellite & aerial imagery platform.

Owns acquisition, raster processing, storage, metadata, time-series, tiles, and jobs for
spaceborne and manned-airborne imagery. Does NOT own drone/UAV missions or imagery (see the
``drone`` context). Depends only on the shared kernel; collaborates with other contexts via
ids + integration events. See ``README.md`` and ``docs/adr/0005``, ``docs/adr/0010``.
"""
