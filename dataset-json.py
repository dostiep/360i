from saxonche import PySaxonProcessor
from datetime import datetime
import json
from jsonschema import validate, ValidationError

define_file = "define-2-1-ADaM.xml"

# Load Dataset-JSON 1.1 Schema
with open("dataset.schema.json") as schemajson:
    schema = schemajson.read()
schema = json.loads(schema)

processor = PySaxonProcessor(license=False)

# Extract domains/analysis datasets names from Define.xml and loop through to create Dataset-JSON shells
executable = processor.new_xslt30_processor().compile_stylesheet(stylesheet_file="Extract-list-DS.xsl")

for ds in executable.transform_to_string(xdm_node=processor.parse_xml(xml_file_name=define_file)).split(","):
    executable_ds = processor.new_xslt30_processor().compile_stylesheet(stylesheet_file="Dataset-JSON.xsl")
    executable_ds.set_parameter("dsName", processor.make_string_value(ds))
    executable_ds.set_parameter("datasetJSONCreationDateTime", processor.make_string_value(datetime.now().strftime('%Y-%m-%dT%H:%M:%S')))
    try:
        json_data = json.loads(executable_ds.transform_to_string(xdm_node=processor.parse_xml(xml_file_name=define_file)))
        validate(json_data, schema)
        with open(ds + ".json", "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)
    except ValidationError as e:
        print("Validation failed:", e.message)
