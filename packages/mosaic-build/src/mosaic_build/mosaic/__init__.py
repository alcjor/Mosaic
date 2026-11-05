"""The mosaic builder (Specification 0.1, section 7).

A build runs eight steps (section 7.1). Implemented so far:

1. **Check** (:mod:`mosaic_build.mosaic.pieces`): check the pattern and proposals, resolve and
   open the pieces;
2. **Map** (:mod:`mosaic_build.mosaic.map`): piece nodes to canonical nodes by the field maps,
   with ``strip`` and the normalisation steps of :mod:`mosaic_build.mosaic.normalise`;
3. **Merge** (:mod:`mosaic_build.mosaic.merge`): one node per type and key, values by piece
   priority, conflicts recorded, aliases, external references, evidence and sources.

The builder uses no AI and no network, and the same inputs give the same result.
"""

from mosaic_build.mosaic.errors import BuildError
from mosaic_build.mosaic.map import map_nodes
from mosaic_build.mosaic.merge import Assembly, merge
from mosaic_build.mosaic.pieces import Inputs, check

__all__ = ["Assembly", "BuildError", "Inputs", "check", "map_nodes", "merge"]
