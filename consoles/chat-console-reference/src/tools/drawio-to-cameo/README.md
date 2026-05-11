# Draw.io to Cameo XMI Converter

Converts Draw.io (.drawio) diagrams to XMI format for import into Cameo Systems Modeler / MagicDraw.

## Usage

```bash
# Basic conversion (SysML BDD by default)
python3 drawio_to_cameo.py diagram.drawio -o output.xmi

# Specify profile and diagram type
python3 drawio_to_cameo.py diagram.drawio --profile sysml --diagram-type bdd

# With custom model name
python3 drawio_to_cameo.py diagram.drawio --model-name "My Architecture"

# Verbose output
python3 drawio_to_cameo.py diagram.drawio -o output.xmi -v
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `-o, --output` | Output .xmi file path | `<input>.xmi` |
| `--profile` | `sysml` or `uml` | `sysml` |
| `--diagram-type` | `bdd`, `ibd`, `activity`, `sequence`, `class` | `bdd` |
| `--model-name` | Name for the UML/SysML model | filename |
| `--mappings` | Custom shape mappings JSON | built-in |
| `-v, --verbose` | Verbose output | off |

## Diagram Types

- **bdd** - Block Definition Diagram (SysML)
- **ibd** - Internal Block Diagram (SysML)
- **activity** - Activity Diagram
- **sequence** - Sequence Diagram
- **class** - Class Diagram (UML)

## Shape Mappings

The converter maps Draw.io shapes to SysML/UML elements:

| Draw.io Shape | SysML Type | UML Type |
|---------------|------------|----------|
| Swimlane | Block | Class |
| Rounded rectangle | Block | Class |
| Ellipse | Activity | Activity |
| Diamond | DecisionNode | DecisionNode |
| Cylinder | Block (dataStore) | Class |
| Actor | Actor | Actor |
| Text | Comment | Comment |
| AWS shapes | Block (aws_resource) | Class |

## Importing into Cameo

1. Run the converter to generate the XMI file
2. In Cameo: **File > Import From > XMI...**
3. Select the generated `.xmi` file
4. Choose import options:
   - Select "Import all" or specific packages
   - Enable "Create diagram" if desired
5. Click **OK**

### Post-Import Steps

After import, you may want to:

1. **Apply stereotypes** - The converter adds stereotype hints as comments. Apply actual SysML stereotypes in Cameo.
2. **Arrange layout** - Position comments reference original Draw.io coordinates for guidance.
3. **Create diagrams** - Add imported elements to BDD/IBD diagrams.
4. **Refine relationships** - Convert Associations to Compositions/Aggregations as needed.

## Custom Mappings

Create a custom `shape_mappings.json` to override default mappings:

```json
{
  "shape_mappings": {
    "custom_shape": {
      "sysml_type": "Block",
      "uml_type": "Class",
      "stereotype": "myStereotype"
    }
  }
}
```

Use with: `--mappings custom_mappings.json`

## Limitations

- **Semantic loss**: Draw.io diagrams are visual; XMI captures semantic model structure. Some visual elements become Comments.
- **No containment**: Parent-child relationships in Draw.io don't automatically become UML/SysML containment.
- **Stereotypes as comments**: True stereotype application requires post-import work in Cameo.
- **Diagram layout**: Cameo may not preserve exact Draw.io layout; position hints are in comments.

## EA Workflow Recommendation

1. EAs create diagrams in Draw.io using standard shapes
2. Run converter to generate XMI
3. Modeler imports XMI into Cameo
4. Modeler applies proper SysML stereotypes and creates diagram views
5. Iterate: EAs update Draw.io → re-convert → re-import delta

## Files

- `drawio_to_cameo.py` - Main converter script
- `shape_mappings.json` - Shape-to-SysML/UML mappings
- `test_output/` - Test conversion outputs
