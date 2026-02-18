"""Default handler registry for the knowledge pipeline."""

from api.pipeline.handler import Handler, HandlerType
from api.pipeline.handlers.rid_handlers import (
    block_self_referential,
    extract_entity_type,
    forget_delete_and_stop,
    set_forget_flag,
)
from api.pipeline.handlers.bundle_handlers import (
    entity_type_validator,
    cross_reference_resolver,
)
from api.pipeline.handlers.final_handlers import log_processing_result

DEFAULT_HANDLERS = [
    # RID phase
    Handler(handler_type=HandlerType.RID, fn=block_self_referential),  # P3b
    Handler(handler_type=HandlerType.RID, fn=set_forget_flag),
    Handler(handler_type=HandlerType.RID, fn=forget_delete_and_stop),
    Handler(handler_type=HandlerType.RID, fn=extract_entity_type),
    # Manifest phase — empty (no-op by design)
    # Bundle phase
    Handler(handler_type=HandlerType.Bundle, fn=entity_type_validator),  # P3b
    Handler(handler_type=HandlerType.Bundle, fn=cross_reference_resolver),
    # Network phase — empty (deferred until WEBHOOK/push)
    # Final phase
    Handler(handler_type=HandlerType.Final, fn=log_processing_result),
]
