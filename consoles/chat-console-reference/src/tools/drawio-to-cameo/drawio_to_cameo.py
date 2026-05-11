#!/usr/bin/env python3
"""
Draw.io to Cameo XMI Converter

Converts Draw.io (.drawio) diagrams to XMI format for import into
Cameo Systems Modeler / MagicDraw.

Usage:
    python drawio_to_cameo.py input.drawio -o output.xmi
    python drawio_to_cameo.py input.drawio --profile sysml
    python drawio_to_cameo.py input.drawio --diagram-type bdd

Author: [ENTERPRISE: org identifier]
Version: 1.0.0
"""

import argparse
import json
import re
import sys
import uuid
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime
from html import unescape
from pathlib import Path
from typing import Optional
from urllib.parse import unquote


@dataclass
class DrawioElement:
    """Represents a parsed Draw.io element."""
    id: str
    value: str
    style: dict
    geometry: dict
    parent_id: Optional[str] = None
    source_id: Optional[str] = None  # For edges
    target_id: Optional[str] = None  # For edges
    is_edge: bool = False
    children: list = field(default_factory=list)

    @property
    def clean_value(self) -> str:
        """Strip HTML and return clean text."""
        text = unescape(self.value or "")
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', ' ', text)
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    @property
    def shape_type(self) -> str:
        """Determine the shape type from style."""
        style = self.style

        # Check for specific shapes
        if 'swimlane' in str(style):
            return 'swimlane'
        if 'ellipse' in str(style):
            return 'ellipse'
        if 'rhombus' in str(style):
            return 'rhombus'
        if 'cylinder' in str(style):
            return 'cylinder'
        if 'actor' in str(style):
            return 'actor'
        if 'document' in str(style):
            return 'document'
        if 'cloud' in str(style):
            return 'cloud'
        if 'text' in str(style) or self.style.get('shape') == 'text':
            return 'text'

        # Check for AWS shapes
        shape = style.get('shape', '')
        if 'mxgraph.aws4' in shape:
            return shape

        # Check for process/rounded
        if style.get('rounded') == '1' or 'rounded=1' in str(style):
            return 'rounded'

        return 'generic'


@dataclass
class XMIElement:
    """Represents an XMI model element."""
    xmi_id: str
    name: str
    xmi_type: str
    stereotype: Optional[str] = None
    properties: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    source_drawio_id: Optional[str] = None


class DrawioParser:
    """Parses Draw.io XML files."""

    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        self.elements: dict[str, DrawioElement] = {}
        self.edges: list[DrawioElement] = []
        self.root_elements: list[str] = []

    def parse(self) -> dict[str, DrawioElement]:
        """Parse the Draw.io file and return elements."""
        tree = ET.parse(self.filepath)
        root = tree.getroot()

        # Find the mxGraphModel
        diagram = root.find('.//diagram')
        if diagram is None:
            raise ValueError("No diagram found in Draw.io file")

        graph_model = diagram.find('.//mxGraphModel')
        if graph_model is None:
            raise ValueError("No mxGraphModel found in diagram")

        # Parse all mxCell elements
        root_elem = graph_model.find('root')
        if root_elem is None:
            raise ValueError("No root element found in mxGraphModel")

        for cell in root_elem.findall('mxCell'):
            element = self._parse_cell(cell)
            if element:
                self.elements[element.id] = element

                # Track edges separately
                if element.is_edge:
                    self.edges.append(element)
                elif element.parent_id in ('0', '1', None):
                    self.root_elements.append(element.id)

        # Build parent-child relationships
        for elem_id, elem in self.elements.items():
            if elem.parent_id and elem.parent_id in self.elements:
                self.elements[elem.parent_id].children.append(elem_id)

        return self.elements

    def _parse_cell(self, cell: ET.Element) -> Optional[DrawioElement]:
        """Parse a single mxCell element."""
        cell_id = cell.get('id')

        # Skip the root cells (0 and 1)
        if cell_id in ('0', '1'):
            return None

        value = cell.get('value', '')
        style_str = cell.get('style', '')
        parent_id = cell.get('parent')
        source_id = cell.get('source')
        target_id = cell.get('target')
        is_edge = cell.get('edge') == '1'

        # Parse style string into dict
        style = self._parse_style(style_str)

        # Parse geometry
        geometry = {}
        geom_elem = cell.find('mxGeometry')
        if geom_elem is not None:
            geometry = {
                'x': float(geom_elem.get('x', 0)),
                'y': float(geom_elem.get('y', 0)),
                'width': float(geom_elem.get('width', 0)),
                'height': float(geom_elem.get('height', 0))
            }

        return DrawioElement(
            id=cell_id,
            value=value,
            style=style,
            geometry=geometry,
            parent_id=parent_id,
            source_id=source_id,
            target_id=target_id,
            is_edge=is_edge
        )

    def _parse_style(self, style_str: str) -> dict:
        """Parse Draw.io style string into dictionary."""
        style = {}
        if not style_str:
            return style

        # Handle shape= prefix
        if style_str.startswith('shape='):
            parts = style_str.split(';')
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    style[key] = value
                elif part:
                    style[part] = True
        else:
            # Standard key=value format
            parts = style_str.split(';')
            for part in parts:
                if '=' in part:
                    key, value = part.split('=', 1)
                    style[key] = value
                elif part:
                    style[part] = True

        return style


class XMIGenerator:
    """Generates XMI output for Cameo import."""

    XMI_NAMESPACE = "http://www.omg.org/spec/XMI/20131001"
    UML_NAMESPACE = "http://www.omg.org/spec/UML/20131001"
    SYSML_NAMESPACE = "http://www.omg.org/spec/SysML/20150709/SysML"

    def __init__(self, mappings_file: Optional[str] = None):
        self.mappings = self._load_mappings(mappings_file)
        self.xmi_elements: list[XMIElement] = []
        self.id_map: dict[str, str] = {}  # drawio_id -> xmi_id

    def _load_mappings(self, mappings_file: Optional[str]) -> dict:
        """Load shape mappings from JSON file."""
        if mappings_file is None:
            # Use default mappings file in same directory
            mappings_file = Path(__file__).parent / 'shape_mappings.json'

        with open(mappings_file, 'r') as f:
            return json.load(f)

    def _generate_xmi_id(self, prefix: str = "elem") -> str:
        """Generate a unique XMI ID."""
        return f"_{prefix}_{uuid.uuid4().hex[:12]}"

    def convert(self, elements: dict[str, DrawioElement],
                edges: list[DrawioElement],
                diagram_type: str = "bdd") -> list[XMIElement]:
        """Convert Draw.io elements to XMI elements."""

        # First pass: create XMI elements for all non-edge Draw.io elements
        for elem_id, elem in elements.items():
            if not elem.is_edge:
                xmi_elem = self._convert_element(elem, diagram_type)
                if xmi_elem:
                    self.xmi_elements.append(xmi_elem)
                    self.id_map[elem_id] = xmi_elem.xmi_id

        # Second pass: convert edges to associations/connectors
        for edge in edges:
            xmi_edge = self._convert_edge(edge)
            if xmi_edge:
                self.xmi_elements.append(xmi_edge)

        return self.xmi_elements

    def _convert_element(self, elem: DrawioElement,
                         diagram_type: str) -> Optional[XMIElement]:
        """Convert a single Draw.io element to XMI."""
        shape_type = elem.shape_type
        name = elem.clean_value or f"Element_{elem.id}"

        # Look up mapping
        mapping = self._get_mapping(shape_type)

        xmi_id = self._generate_xmi_id()

        # Determine XMI type based on diagram type
        if diagram_type in ("bdd", "ibd"):
            xmi_type = mapping.get('sysml_type', 'Block')
        else:
            xmi_type = mapping.get('uml_type', 'Class')

        stereotype = mapping.get('stereotype')

        # Handle AWS-specific shapes
        if shape_type.startswith('mxgraph.aws4'):
            aws_mapping = self.mappings.get('aws_shape_mappings', {}).get(shape_type, {})
            if not name or name.startswith('Element_'):
                name = aws_mapping.get('name_suffix', shape_type.split('.')[-1])
            stereotype = aws_mapping.get('stereotype', 'aws_resource')

        # Store geometry and style info in properties
        properties = {
            'drawio_id': elem.id,
            'geometry': elem.geometry,
            'original_style': elem.style
        }

        return XMIElement(
            xmi_id=xmi_id,
            name=name,
            xmi_type=xmi_type,
            stereotype=stereotype,
            properties=properties,
            source_drawio_id=elem.id
        )

    def _convert_edge(self, edge: DrawioElement) -> Optional[XMIElement]:
        """Convert a Draw.io edge to XMI association/connector."""
        if not edge.source_id or not edge.target_id:
            return None

        source_xmi_id = self.id_map.get(edge.source_id)
        target_xmi_id = self.id_map.get(edge.target_id)

        if not source_xmi_id or not target_xmi_id:
            return None

        xmi_id = self._generate_xmi_id("conn")
        name = edge.clean_value or ""

        # Determine edge type
        style = edge.style
        if style.get('dashed') == '1':
            xmi_type = 'Dependency'
        else:
            xmi_type = 'Association'

        properties = {
            'source_xmi_id': source_xmi_id,
            'target_xmi_id': target_xmi_id,
            'drawio_id': edge.id,
            'edge_label': name
        }

        return XMIElement(
            xmi_id=xmi_id,
            name=name,
            xmi_type=xmi_type,
            properties=properties,
            source_drawio_id=edge.id
        )

    def _get_mapping(self, shape_type: str) -> dict:
        """Get the mapping for a shape type."""
        shape_mappings = self.mappings.get('shape_mappings', {})

        # Direct match
        if shape_type in shape_mappings:
            return shape_mappings[shape_type]

        # Partial match for AWS shapes
        for key, mapping in shape_mappings.items():
            if key in shape_type:
                return mapping

        # Default to generic block
        return {
            'sysml_type': 'Block',
            'uml_type': 'Class',
            'stereotype': None
        }

    def generate_xmi(self, model_name: str = "DrawioImport",
                     profile: str = "sysml") -> str:
        """Generate XMI XML string."""

        # Create XMI root
        xmi = ET.Element('xmi:XMI')
        xmi.set('xmlns:xmi', self.XMI_NAMESPACE)
        xmi.set('xmlns:uml', self.UML_NAMESPACE)

        if profile == "sysml":
            xmi.set('xmlns:sysml', self.SYSML_NAMESPACE)

        xmi.set('xmi:version', '2.5.1')

        # Create Documentation element
        doc = ET.SubElement(xmi, 'xmi:Documentation')
        doc.set('exporter', 'DrawioToCameo')
        doc.set('exporterVersion', '1.0.0')
        doc.set('exporterID', '[ENTERPRISE: org identifier]')

        # Create Model
        model = ET.SubElement(xmi, 'uml:Model')
        model.set('xmi:type', 'uml:Model')
        model.set('xmi:id', self._generate_xmi_id("model"))
        model.set('name', model_name)

        # Add stereotype applications if SysML
        if profile == "sysml":
            self._add_sysml_profile_application(model)

        # Create package for imported elements
        package = ET.SubElement(model, 'packagedElement')
        package.set('xmi:type', 'uml:Package')
        package.set('xmi:id', self._generate_xmi_id("pkg"))
        package.set('name', 'ImportedDiagram')

        # Add elements
        for elem in self.xmi_elements:
            if elem.xmi_type in ('Association', 'Dependency'):
                self._add_relationship(package, elem)
            else:
                self._add_element(package, elem, profile)

        # Convert to string with proper formatting
        self._indent(xmi)
        return ET.tostring(xmi, encoding='unicode', xml_declaration=True)

    def _add_sysml_profile_application(self, model: ET.Element):
        """Add SysML profile application to model."""
        profile_app = ET.SubElement(model, 'profileApplication')
        profile_app.set('xmi:type', 'uml:ProfileApplication')
        profile_app.set('xmi:id', self._generate_xmi_id("prof"))

        applied_profile = ET.SubElement(profile_app, 'appliedProfile')
        applied_profile.set('xmi:type', 'uml:Profile')
        applied_profile.set('href', 'http://www.omg.org/spec/SysML/20150709/SysML.xmi#SysML')

    def _add_element(self, parent: ET.Element, elem: XMIElement,
                     profile: str):
        """Add an element to the XMI tree."""
        pkg_elem = ET.SubElement(parent, 'packagedElement')

        # Set type based on profile
        if profile == "sysml" and elem.xmi_type == 'Block':
            pkg_elem.set('xmi:type', 'uml:Class')
        else:
            pkg_elem.set('xmi:type', f'uml:{elem.xmi_type}')

        pkg_elem.set('xmi:id', elem.xmi_id)
        pkg_elem.set('name', elem.name)

        # Add stereotype if present
        if elem.stereotype:
            # Add stereotype reference as ownedComment (simplified approach)
            comment = ET.SubElement(pkg_elem, 'ownedComment')
            comment.set('xmi:type', 'uml:Comment')
            comment.set('xmi:id', self._generate_xmi_id("cmt"))
            body = ET.SubElement(comment, 'body')
            body.text = f"<<{elem.stereotype}>> Imported from Draw.io"

        # Add geometry as tagged value comment
        if 'geometry' in elem.properties:
            geom = elem.properties['geometry']
            geom_comment = ET.SubElement(pkg_elem, 'ownedComment')
            geom_comment.set('xmi:type', 'uml:Comment')
            geom_comment.set('xmi:id', self._generate_xmi_id("geom"))
            body = ET.SubElement(geom_comment, 'body')
            body.text = f"Position: x={geom.get('x', 0)}, y={geom.get('y', 0)}, w={geom.get('width', 0)}, h={geom.get('height', 0)}"

    def _add_relationship(self, parent: ET.Element, elem: XMIElement):
        """Add a relationship (association/dependency) to the XMI tree."""
        pkg_elem = ET.SubElement(parent, 'packagedElement')
        pkg_elem.set('xmi:type', f'uml:{elem.xmi_type}')
        pkg_elem.set('xmi:id', elem.xmi_id)

        if elem.name:
            pkg_elem.set('name', elem.name)

        source_id = elem.properties.get('source_xmi_id')
        target_id = elem.properties.get('target_xmi_id')

        if elem.xmi_type == 'Association':
            # Add member ends
            member_end_1 = ET.SubElement(pkg_elem, 'memberEnd')
            member_end_1.set('xmi:idref', f"{elem.xmi_id}_end1")

            member_end_2 = ET.SubElement(pkg_elem, 'memberEnd')
            member_end_2.set('xmi:idref', f"{elem.xmi_id}_end2")

            # Add owned ends
            owned_end_1 = ET.SubElement(pkg_elem, 'ownedEnd')
            owned_end_1.set('xmi:type', 'uml:Property')
            owned_end_1.set('xmi:id', f"{elem.xmi_id}_end1")
            owned_end_1.set('type', source_id)

            owned_end_2 = ET.SubElement(pkg_elem, 'ownedEnd')
            owned_end_2.set('xmi:type', 'uml:Property')
            owned_end_2.set('xmi:id', f"{elem.xmi_id}_end2")
            owned_end_2.set('type', target_id)

        elif elem.xmi_type == 'Dependency':
            # Add client and supplier
            client = ET.SubElement(pkg_elem, 'client')
            client.set('xmi:idref', source_id)

            supplier = ET.SubElement(pkg_elem, 'supplier')
            supplier.set('xmi:idref', target_id)

    def _indent(self, elem: ET.Element, level: int = 0):
        """Add proper indentation to XML elements."""
        indent = "\n" + "  " * level
        if len(elem):
            if not elem.text or not elem.text.strip():
                elem.text = indent + "  "
            if not elem.tail or not elem.tail.strip():
                elem.tail = indent
            for child in elem:
                self._indent(child, level + 1)
            if not child.tail or not child.tail.strip():
                child.tail = indent
        else:
            if level and (not elem.tail or not elem.tail.strip()):
                elem.tail = indent


class DrawioToCameoConverter:
    """Main converter class."""

    def __init__(self, mappings_file: Optional[str] = None):
        self.mappings_file = mappings_file

    def convert(self, input_file: str, output_file: str,
                model_name: Optional[str] = None,
                profile: str = "sysml",
                diagram_type: str = "bdd") -> dict:
        """
        Convert a Draw.io file to XMI.

        Args:
            input_file: Path to .drawio file
            output_file: Path for output .xmi file
            model_name: Name for the UML/SysML model
            profile: "sysml" or "uml"
            diagram_type: "bdd", "ibd", "activity", "sequence"

        Returns:
            dict with conversion statistics
        """
        input_path = Path(input_file)
        output_path = Path(output_file)

        if model_name is None:
            model_name = input_path.stem

        # Parse Draw.io file
        parser = DrawioParser(input_file)
        elements = parser.parse()

        # Generate XMI
        generator = XMIGenerator(self.mappings_file)
        xmi_elements = generator.convert(elements, parser.edges, diagram_type)
        xmi_output = generator.generate_xmi(model_name, profile)

        # Write output
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(xmi_output)

        # Calculate statistics
        stats = {
            'input_file': str(input_path),
            'output_file': str(output_path),
            'elements_parsed': len(elements),
            'edges_parsed': len(parser.edges),
            'xmi_elements_created': len(xmi_elements),
            'profile': profile,
            'diagram_type': diagram_type,
            'model_name': model_name
        }

        return stats


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description='Convert Draw.io diagrams to Cameo XMI format',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s diagram.drawio -o output.xmi
  %(prog)s diagram.drawio --profile sysml --diagram-type bdd
  %(prog)s diagram.drawio --model-name "My Architecture"

Diagram Types:
  bdd      Block Definition Diagram (SysML)
  ibd      Internal Block Diagram (SysML)
  activity Activity Diagram
  sequence Sequence Diagram
  class    Class Diagram (UML)
        """
    )

    parser.add_argument('input', help='Input .drawio file')
    parser.add_argument('-o', '--output',
                        help='Output .xmi file (default: input_name.xmi)')
    parser.add_argument('--profile', choices=['sysml', 'uml'],
                        default='sysml',
                        help='UML/SysML profile (default: sysml)')
    parser.add_argument('--diagram-type',
                        choices=['bdd', 'ibd', 'activity', 'sequence', 'class'],
                        default='bdd',
                        help='Target diagram type (default: bdd)')
    parser.add_argument('--model-name',
                        help='Name for the model (default: filename)')
    parser.add_argument('--mappings',
                        help='Custom shape mappings JSON file')
    parser.add_argument('-v', '--verbose', action='store_true',
                        help='Verbose output')

    args = parser.parse_args()

    # Determine output filename
    input_path = Path(args.input)
    if args.output:
        output_path = args.output
    else:
        output_path = input_path.with_suffix('.xmi')

    # Run conversion
    try:
        converter = DrawioToCameoConverter(args.mappings)
        stats = converter.convert(
            input_file=args.input,
            output_file=output_path,
            model_name=args.model_name,
            profile=args.profile,
            diagram_type=args.diagram_type
        )

        print(f"Conversion complete!")
        print(f"  Input:    {stats['input_file']}")
        print(f"  Output:   {stats['output_file']}")
        print(f"  Elements: {stats['elements_parsed']} parsed, "
              f"{stats['xmi_elements_created']} created")
        print(f"  Edges:    {stats['edges_parsed']} parsed")
        print(f"  Profile:  {stats['profile']}")
        print(f"  Type:     {stats['diagram_type']}")

        if args.verbose:
            print(f"\nModel name: {stats['model_name']}")

    except FileNotFoundError:
        print(f"Error: Input file not found: {args.input}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
