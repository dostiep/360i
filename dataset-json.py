from saxonche import PySaxonProcessor
from datetime import datetime
import json
from jsonschema import validate, ValidationError


# Add --define_file required parameter
import argparse

parser = argparse.ArgumentParser(description="Process Dataset-JSON shells.")
parser.add_argument(
    "--define_file", required=True, help="Path to Define.xml file (required flag)"
)
parser.add_argument(
    "--output_dir",
    required=True,
    help="Directory to write generated files (required flag)",
)
args = parser.parse_args()
define_file = args.define_file
output_dir = args.output_dir

# Load Dataset-JSON 1.1 Schema
with open("dataset.schema.json") as schemajson:
    schema = schemajson.read()
schema = json.loads(schema)

processor = PySaxonProcessor(license=False)

# Extract domains/analysis datasets names from Define.xml and loop through to create Dataset-JSON shells
executable = processor.new_xslt30_processor().compile_stylesheet(
    stylesheet_file="Extract-list-DS.xsl"
)

for ds in executable.transform_to_string(
    xdm_node=processor.parse_xml(xml_file_name=define_file)
).split(","):
    executable_ds = processor.new_xslt30_processor().compile_stylesheet(
        stylesheet_file="Dataset-JSON.xsl"
    )
    executable_ds.set_parameter("dsName", processor.make_string_value(ds))
    executable_ds.set_parameter(
        "datasetJSONCreationDateTime",
        processor.make_string_value(datetime.now().strftime("%Y-%m-%dT%H:%M:%S")),
    )
    try:
        json_data = json.loads(
            executable_ds.transform_to_string(
                xdm_node=processor.parse_xml(xml_file_name=define_file)
            )
        )
        # Write the generated JSON to the output directory
        output_path = f"{output_dir}/{ds}.json"
        with open(output_path, "w") as out_f:
            json.dump(json_data, out_f, indent=2)
        validate(json_data, schema)
        with open(ds + ".json", "w", encoding="utf-8") as f:
            json.dump(json_data, f, indent=4, ensure_ascii=False)
    except ValidationError as e:
        print("Validation failed:", e.message)
