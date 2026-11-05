"""
Máquina de estados de Shipment.

Única fuente de verdad sobre qué transiciones son válidas. Routers y
tareas de Celery deben cambiar el estado SIEMPRE a través de
`transition()`, nunca asignando `shipment.status` directamente.
"""
from models import Shipment, ShipmentStatus

S = ShipmentStatus

ALLOWED_TRANSITIONS: dict[ShipmentStatus, set[ShipmentStatus]] = {
    S.PENDING_PAYMENT: {S.PAID, S.CANCELED},
    S.PAID: {S.LABEL_CREATED, S.CANCELED},
    S.LABEL_CREATED: {S.IN_TRANSIT, S.CANCELED},
    S.IN_TRANSIT: {S.DELIVERED},
    S.DELIVERED: set(),
    S.CANCELED: set(),
}

# Estados en los que el paquete ya está en manos de FedEx: no se puede cancelar.
NON_CANCELABLE = {S.IN_TRANSIT, S.DELIVERED}


class InvalidTransitionError(Exception):
    def __init__(self, current: ShipmentStatus, target: ShipmentStatus):
        self.current = current
        self.target = target
        super().__init__(f"Transición inválida: {current.value} -> {target.value}")


def can_transition(current: ShipmentStatus, target: ShipmentStatus) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def transition(shipment: Shipment, target: ShipmentStatus) -> None:
    current = ShipmentStatus(shipment.status)
    if not can_transition(current, target):
        raise InvalidTransitionError(current, target)
    shipment.status = target
