from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status

from flare.steering import Actor

#: Header carrying the acting user id until OIDC lands.
ACTOR_HEADER = "X-Flare-Actor"


async def current_actor(
    x_flare_actor: Annotated[str | None, Header(alias=ACTOR_HEADER)] = None,
) -> Actor:
    """Resolve the human making this write, or 401."""
    if not x_flare_actor or not x_flare_actor.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"{ACTOR_HEADER} header is required for steering writes",
        )
    return Actor(user_id=x_flare_actor.strip(), surface="api")


ActorDep = Annotated[Actor, Depends(current_actor)]