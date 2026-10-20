"""Construct supported electrical-component graphics items from type values.

Keeping construction in this module gives the palette, canvas, and importer a
single place to create consistently initialized components.
"""

from components.electrical_component import ElectricalComponent, ComponentType

class ComponentFactory:
    """Central constructor for supported ElectricalComponent instances."""
    
    @staticmethod
    def create_component(comp_type, grid_x, grid_y):
        """Create a component of the specified type at a grid position.

        Args:
            comp_type: ComponentType enum value to construct.
            grid_x: Horizontal coordinate in grid units.
            grid_y: Vertical coordinate in grid units.

        Returns:
            A consistently initialized ElectricalComponent instance.
        """
        component = ElectricalComponent(comp_type, grid_x, grid_y)
        return component
    
    @staticmethod
    def get_available_components():
        """Return component types exposed by the placement palette."""
        return [
            ComponentType.RESISTOR,
            ComponentType.CAPACITOR,
            ComponentType.INDUCTOR,
            ComponentType.VOLTAGE_SOURCE,
            ComponentType.CURRENT_SOURCE,
            ComponentType.NODE,
        ]
