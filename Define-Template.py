import json
import os
import argparse
from jsonata import Jsonata
from cdisc_library_client import CDISCLibraryClient
from collections import defaultdict
from dotenv import load_dotenv


# Load environment variables
load_dotenv()

# Parse arguments
parser = argparse.ArgumentParser(description="Process USDM JSON file.")
parser.add_argument(
    "--usdm_file", required=True, help="Path to USDM JSON file (required flag)"
)
parser.add_argument(
    "--output_template",
    required=True,
    help="Path to output template JSON file (required flag)",
)
parser.add_argument(
    "--cdisc_api_key",
    required=False,
    help="CDISC Library API Key (optional, defaults to environment variable)",
)
args = parser.parse_args()

# Initialize CDISC Library Client
api_key = args.cdisc_api_key if args.cdisc_api_key else os.getenv("CDISC_API_KEY")
client = CDISCLibraryClient(api_key=api_key)


# Load USDM data
with open(args.usdm_file, "r") as file:
    usdm_data = json.load(file)


# Parameters: those are assumptions for the purpose of this script.
studyversion = 0
docversion = 0
sdtmig = "3.4"
sdtmct = "2025-03-28"


# Initialize template structure
template = {"Study": {}, "Standards": {}, "Datasets": {}, "CodeLists": {}}


# Initialize temporary data structures
datasets_dict = {}
bc_dict = {}
vlm_lookup = {}
all_codelists = []
test_dict = {}


# Extract Biomedical Concepts from USDM
expression_bcs = Jsonata(f'study.versions["{studyversion}"].biomedicalConcepts')
biomedical_concepts = expression_bcs.evaluate(usdm_data)


def process_bc():
    """
    Iterates through all biomedical concepts and processes them based on their type,
    populating the datasets_dict and bc_dict data structures.
    """
    for bc in biomedical_concepts:
        # Extract biomedical concept data and type
        bc_data = client.get_api_json("/cosmos/v2" + bc["reference"])
        concept_type = bc_data["_links"]["self"]["type"]

        if concept_type == "Biomedical Concept":
            process_bc_type(bc, bc_data)
        elif concept_type == "SDTM Dataset Specialization":
            process_dss_type(bc, bc_data)


def process_bc_type(bc, bc_data):
    """
    Processes a biomedical concept of type 'Biomedical Concept', extracting dataset specializations
    and their variables, and updating the datasets_dict data structure.

    Args:
        bc (dict): The biomedical concept being processed.
        bc_data (dict): Detailed data for the biomedical concept.
    """
    dss_response = client.get_api_json(
        f"/cosmos/v2/mdr/specializations/datasetspecializations?biomedicalconcept={bc_data['conceptId']}"
    )
    dataset_links = dss_response["_links"]["datasetSpecializations"]["sdtm"]

    for dataset_link in dataset_links:
        dataset_data = client.get_api_json("/cosmos/v2" + dataset_link["href"])
        dataset_name = dataset_data["domain"]
        variables = dataset_data.get("variables", [])

        # Process variables within current biomedical concept
        process_variables(variables, dataset_name, bc)


def process_dss_type(bc, bc_data):
    """
    Processes a biomedical concept of type 'SDTM Dataset Specialization', extracting variables,
    building where clauses, and updating both bc_dict and datasets_dict data structures.

    Args:
        bc (dict): The biomedical concept being processed.
        bc_data (dict): Detailed data for the dataset specialization.
    """
    dss_response = client.get_api_json(
        f"/cosmos/v2/mdr/specializations/sdtm/datasetspecializations/{bc_data['datasetSpecializationId']}"
    )

    dataset_name = dss_response["domain"]
    variables = dss_response.get("variables", [])

    # Process variables within current biomedical concept
    process_variables(variables, dataset_name, bc)

    # # Build WhereClause for variables with comparators
    where_clause = build_where_clause(bc, bc_data, dss_response, dataset_name)

    # # Initialize biomedical concepts dictionary entry if not exists
    if bc["id"] not in bc_dict:
        bc_dict[bc["id"]] = []

    # # Process VLM target variables
    process_vlm_target_variables(bc, bc_data, where_clause)


def process_variables(variables, dataset_name, bc):
    """
    Processes variables for a given dataset, extracting response codes from biomedical concepts.

    Args:
        variables (list): List of variable dictionaries to process.
        dataset_name (str): The name of the dataset these variables belong to.
        bc (dict): The biomedical concept.
    """
    # Initialize datasets dictionary entry if not exists
    if dataset_name not in datasets_dict:
        datasets_dict[dataset_name] = {}

    # Process each variable in the DSS only if they have a dataElementConceptId
    for variable in variables:
        variable_name = variable.get("name")
        data_element_concept_id = variable.get("dataElementConceptId")
        codelist_concept_id = variable.get("codelist", {}).get("conceptId")

        if variable_name and data_element_concept_id:

            # Initialize datasets dictionary entry if not exists for this variable
            if variable_name not in datasets_dict[dataset_name]:
                datasets_dict[dataset_name][variable_name] = {}

            for property in bc["properties"]:
                property_code = property["code"]["standardCode"]["code"]

                # Proceed only for the variables found in BC's properties
                if data_element_concept_id == property_code:
                    response_codes = []

                    # Proceed for variables with a known codelist and add submissionValue values
                    if codelist_concept_id:
                        terms = client.get_codelist_terms(
                            f"sdtmct-{sdtmct}/", codelist_concept_id
                        )
                        for response_code in property.get("responseCodes", []):
                            code = response_code.get("code", {}).get("code", "")
                            value = next(
                                (
                                    term
                                    for term in terms
                                    if term.get("conceptId") == code
                                ),
                                None,
                            )
                            if value:
                                response_codes.append(value["submissionValue"])

                        # Initialize datasets dictionary entry if not exists for this variable and codelist ID
                        if (
                            codelist_concept_id
                            not in datasets_dict[dataset_name][variable_name]
                        ):
                            datasets_dict[dataset_name][variable_name][
                                codelist_concept_id
                            ] = []

                        # Add submissionValue values and remove duplicates if any
                        datasets_dict[dataset_name][variable_name][
                            codelist_concept_id
                        ] = list(
                            set(
                                datasets_dict[dataset_name][variable_name][
                                    codelist_concept_id
                                ]
                                + response_codes
                            )
                        )
                    # Create an empty object for variables without a known codelist
                    else:
                        datasets_dict[dataset_name][variable_name] = {}
                    break


def build_where_clause(bc, bc_data, dss_response, dataset_name):
    """
    Builds a list of where clauses for variables with comparators in a biomedical concept.

    Args:
        bc (dict): The biomedical concept being processed.
        bc_data (dict): Detailed data for the biomedical concept.
        dss_response (dict): The dataset specialization being processed.
        dataset_name (str): The dataset name for the variables.

    Returns:
        list: List of where clause dictionaries.
    """
    where_clause = []
    for property in bc["properties"]:
        variable_name = property["name"]
        variable_data = next(
            (var for var in bc_data["variables"] if var.get("name") == variable_name),
            None,
        )

        # Only proceed for variable with 'comparator' and extract terms from codelists
        if variable_data and "comparator" in variable_data:
            codelist_concept_id = variable_data.get("codelist", {}).get("conceptId")
            terms = client.get_codelist_terms(f"sdtmct-{sdtmct}/", codelist_concept_id)

            # Extract submissionValue values if available
            response_values = []
            for response_code in property.get("responseCodes", []):
                code = response_code.get("code", {}).get("code", "")
                value = next(
                    (term for term in terms if term.get("conceptId") == code), None
                )
                if value:
                    response_values.append(value["submissionValue"])

            # Use response_values directly if available, otherwise use either assignedTerm or valueList from DSS
            if not response_values:
                # Find the corresponding variable in dss_response
                dataset_variable = next(
                    (
                        var
                        for var in dss_response["variables"]
                        if var.get("name") == variable_name
                    ),
                    None,
                )

                if dataset_variable:
                    # Check for assignedTerm
                    if (
                        "assignedTerm" in dataset_variable
                        and "conceptId" in dataset_variable["assignedTerm"]
                    ):
                        response_values = [dataset_variable["assignedTerm"]["value"]]
                    # Check for valueList otherwise (array of values)
                    elif (
                        "valueList" in dataset_variable
                        and dataset_variable["valueList"]
                    ):
                        response_values = dataset_variable["valueList"]

            clause_item = {
                "Dataset": dataset_name,
                "Variable": variable_name,
                "Codelist Concept ID": codelist_concept_id,
                "Comparator": variable_data["comparator"],
                "Values": response_values,
            }

            where_clause.append({"Clause": [clause_item]})

    return where_clause


def process_vlm_target_variables(bc, bc_data, where_clause):
    """
    Processes variables that are VLM (Variable Level Metadata) targets, extracting their metadata
    and response codes, and updating the bc_dict.

    Args:
        bc (dict): The biomedical concept being processed.
        bc_data (dict): Detailed data for the biomedical concept.
        where_clause (list): Where clause(s) associated with the variables.
    """
    for property in bc["properties"]:
        variable_name = property["name"]
        variable_data = next(
            (var for var in bc_data["variables"] if var.get("name") == variable_name),
            None,
        )

        # Proceed only for variables that are a vlmTarget
        if (
            variable_data
            and "comparator" not in variable_data
            and variable_data.get("vlmTarget") == True
        ):

            codelist_concept_id = variable_data.get("codelist", {}).get("conceptId")
            terms = client.get_codelist_terms(f"sdtmct-{sdtmct}/", codelist_concept_id)

            # Create VLM data structure
            vlm_data = {}
            vlm_fields = [
                "role",
                "dataType",
                "length",
                "format",
                "significantDigits",
                "originType",
                "originSource",
            ]

            for field in vlm_fields:
                value = variable_data.get(field)
                if value is not None:
                    vlm_data[field] = value

            # Extract submissionValue values if available
            response_values = []
            if terms:
                for response_code in property.get("responseCodes", []):
                    code = response_code.get("code", {}).get("code", "")
                    value = next(
                        (term for term in terms if term.get("conceptId") == code), None
                    )
                    if value:
                        response_values.append(value["submissionValue"])

            # Add response codes if available
            if response_values:
                vlm_data["responseCodes"] = response_values

            # Add WhereClause to VLM data
            vlm_data["WhereClause"] = where_clause

            # Create variable dictionary and add to biomedical concepts
            variable_dict = {variable_name: vlm_data}
            bc_dict[bc["id"]].append(variable_dict)


def build_vlm_lookup():
    """
    Builds a lookup dictionary (vlm_lookup) for quick access to VLM variable metadata
    across all biomedical concepts.
    """
    for concept_list in bc_dict.values():
        for concept_item in concept_list:
            for variable_name, variable_data in concept_item.items():
                if variable_name not in vlm_lookup:
                    vlm_lookup[variable_name] = []
                vlm_lookup[variable_name].append(variable_data)


def update_datasets_dict():
    """
    Updates the datasets_dict dictionary with variable-value pairs extracted from bc_dict,
    ensuring all relevant values are included for each variable in each dataset.
    """
    variable_values = defaultdict(set)

    # Loop through each item of bc_dict data structure
    for concept_data in bc_dict.values():
        # Skip empty concepts
        if not concept_data:
            continue

        # Create variable_values items from WhereClause
        for item in concept_data:
            for field_data in item.values():
                if "WhereClause" in field_data:
                    for where_clause in field_data["WhereClause"]:
                        if "Clause" in where_clause:
                            for clause in where_clause["Clause"]:
                                if (
                                    "Variable" in clause
                                    and "Values" in clause
                                    and "Dataset" in clause
                                ):
                                    dataset = clause["Dataset"]
                                    variable = clause["Variable"]
                                    codelist_concept_id = clause["Codelist Concept ID"]
                                    values = clause["Values"]
                                    key = (variable, dataset, codelist_concept_id)
                                    variable_values[key].update(values)

    # Update dataset dictionary data structure with information from VLM
    for (variable, dataset, codelist_concept_id), values in variable_values.items():
        # Initialize datasets dictionary entry if not exists
        if dataset not in datasets_dict:
            datasets_dict[dataset] = {}
        # Initialize datasets dictionary entry if not exists for this variable
        if variable not in datasets_dict[dataset]:
            datasets_dict[dataset][variable] = {}
        # Initialize datasets dictionary entry if not exists for this variable and codelist ID
        if codelist_concept_id not in datasets_dict[dataset][variable]:
            datasets_dict[dataset][variable][codelist_concept_id] = []

        # Create a special TEST look-up dictionary
        if variable.endswith("TESTCD"):
            terms = client.get_codelist_terms(f"sdtmct-{sdtmct}/", codelist_concept_id)
            response_codes = []
            for value in values:
                term = next(
                    (term for term in terms if term.get("submissionValue") == value),
                    None,
                )
                if term:
                    response_codes.append(term["conceptId"])

            # Initialize dataset in test_dict if not exists
            if dataset not in test_dict:
                test_dict[dataset] = {}

            # Store variable with "CD" suffix removed and its response codes
            test_dict[dataset][variable.replace("TESTCD", "TEST")] = response_codes

        # Merge and deduplicate
        datasets_dict[dataset][variable][codelist_concept_id] = sorted(
            list(
                set(datasets_dict[dataset][variable][codelist_concept_id]).union(values)
            )
        )

        # existing_values = set(datasets_dict[dataset][variable][codelist_concept_id])
        # new_values = set(values)
        # datasets_dict[dataset][variable][codelist_concept_id] = sorted(list(existing_values.union(new_values)))


def populate_study_elements():
    """
    Populates the 'Study' section of the template dictionary with study name, description,
    protocol name, and language, using Jsonata expressions on the USDM data.
    """
    # StudyName Element
    expression_studyname = Jsonata(
        f'study.versions["{studyversion}"].titles[type.decode = "Study Acronym"].text'
    )
    template["Study"]["StudyName"] = expression_studyname.evaluate(usdm_data)

    # StudyDescription Element
    expression_studydescription = Jsonata(
        f'study.versions["{studyversion}"].titles[type.decode = "Official Study Title"].text'
    )
    template["Study"]["StudyDescription"] = expression_studydescription.evaluate(
        usdm_data
    )

    # ProtocolName Element
    expression_protocolname = Jsonata(
        f'study.versions["{studyversion}"].titles[type.decode = "Study Acronym"].text'
    )
    template["Study"]["ProtocolName"] = expression_protocolname.evaluate(usdm_data)

    # Language Element
    expression_language = Jsonata(
        f"""
        (
            $docVersionId := study.versions[{studyversion}].documentVersionIds[{docversion}];
            study.documentedBy[versions[id = $docVersionId]].language.code
        )
    """
    )
    template["Study"]["Language"] = expression_language.evaluate(usdm_data)


def process_datasets():
    """
    Processes all datasets to populate the 'Datasets' section of the template, including
    dataset descriptions, classes, structures, variables, and associated codelists.
    """
    # Loop for each dataset in datasets data strcuture
    for dataset in datasets_dict:
        template["Datasets"][dataset] = {}

        dataset_data = client.get_api_json(
            f"/mdr/sdtmig/{sdtmig.replace('.', '-')}/datasets/{dataset}"
        )

        # Add information to Datasets
        template["Datasets"][dataset]["Description"] = dataset_data["label"]
        template["Datasets"][dataset]["Class"] = dataset_data["_links"]["parentClass"][
            "title"
        ]
        template["Datasets"][dataset]["Structure"] = dataset_data["datasetStructure"]
        template["Datasets"][dataset]["Variables"] = {}

        variable_list = list(datasets_dict[dataset].keys())

        rows_var = []

        # Loop through each variables in datasets data structure or Required/Expected variables from the IG
        for var in (
            v
            for v in dataset_data["datasetVariables"]
            if v["name"] in variable_list or v["core"] in ["Req", "Exp"]
        ):

            codelist_values = []

            # Process codelists if they exist
            if "_links" in var and "codelist" in var["_links"]:
                for codelist_item in var["_links"]["codelist"]:
                    if "href" in codelist_item and codelist_item["href"] is not None:
                        codelist_id = codelist_item["href"].split("/")[-1]
                        codelist_data = client.get_api_json(
                            f"/mdr/ct/packages/sdtmct-{sdtmct}/codelists/{codelist_id}"
                        )
                        codelist_values.append(codelist_data.get("submissionValue", ""))

            row = {
                "Variable": var["name"],
                "Label": var["label"],
                "Data Type": var["simpleDatatype"],
                "Role": var["role"],
            }

            # Only add CodeList key if codelist_values is not empty
            if codelist_values:
                row["CodeList"] = codelist_values

            if var["name"] in vlm_lookup:
                row["VLM"] = vlm_lookup[var["name"]]

            rows_var.append(row)

            # Process to create all_codelists data structure
            if var["name"] in variable_list:
                process_variable_codelist(
                    var, dataset, datasets_dict[dataset][var["name"]]
                )

            else:
                if "_links" in var and "codelist" in var["_links"]:
                    process_variable_codelist(var, dataset)

        # Add variables information for each datasets
        template["Datasets"][dataset]["Variables"] = rows_var

    # Add codelists information
    template["CodeLists"] = all_codelists


def process_variable_codelist(var, dataset, restriction_codes=None):
    """
    Processes a variable's codelists, handling both restricted and unrestricted cases,
    and appends the results to the all_codelists list.

    Args:
        var (dict): The variable being processed.
        dataset (str): The dataset the variable belongs to.
        restriction_codes (dict, optional): Dictionary of codelist restrictions {codelist_id: [codes]}.
                                            If None, variable is processed as unrestricted.
    """
    # Check if variable has a codelist
    if not ("_links" in var and "codelist" in var["_links"]):
        return

    codelist_entries = []

    # Helper function to create term dictionary
    def create_term_dict(term):
        return {
            "NCI Term Code": term.get("conceptId"),
            "Term": term.get("submissionValue"),
            "Decoded Value": term.get("synonyms", []),
        }

    for codelist_item in var["_links"]["codelist"]:
        if not ("href" in codelist_item and codelist_item["href"] is not None):
            continue

        codelist_id = codelist_item["href"].split("/")[-1]
        codelist_data = client.get_api_json(
            f"/mdr/ct/packages/sdtmct-{sdtmct}/codelists/{codelist_id}"
        )
        all_terms = codelist_data.get("terms", [])

        # Determine which terms to include based on different conditions
        if restriction_codes and codelist_id in restriction_codes:
            # Case 1: Variable has restrictions
            restriction_list = restriction_codes[codelist_id]

            if not restriction_list:
                # If restriction list is empty, include all terms
                final_terms = [create_term_dict(term) for term in all_terms]
            else:
                # Filter by restriction codes (using submissionValue)
                final_terms = [
                    create_term_dict(term)
                    for term in all_terms
                    if term.get("submissionValue") in restriction_list
                ]

        elif (
            var["name"].endswith("TEST")
            and dataset in test_dict
            and var["name"] in test_dict[dataset]
        ):
            # Case 2: Variable ends with 'TEST' and has test_dict entry
            final_terms = [
                create_term_dict(term)
                for term in all_terms
                if term.get("conceptId") in test_dict[dataset][var["name"]]
            ]

        else:
            # Case 3: No restrictions - include all terms
            final_terms = [create_term_dict(term) for term in all_terms]

        # Create the codelist entry
        codelist_entry = {
            "NCI Codelist Code": codelist_data.get("conceptId"),
            "Name": codelist_data.get("name"),
            "Short Name": codelist_data.get("submissionValue"),
            "Terms": final_terms,
        }

        codelist_entries.append(codelist_entry)

    # Create the lookup entry with all codelists for this variable
    if codelist_entries:
        transformed_codelist = {
            "Dataset": dataset,
            "Variable": var["name"],
            "CodeList": codelist_entries,
        }
        all_codelists.append(transformed_codelist)


def add_standards():
    """
    Populates the 'Standards' section of the template with SDTMIG and CDISC/NCI standard information.
    """
    template["Standards"] = [
        {"Name": "SDTMIG", "Type": "IG", "Version": sdtmig},
        {
            "Name": "CDISC/NCI",
            "Type": "CT",
            "Publishing Set": "SDTM",
            "Version": sdtmct,
        },
    ]


def save_output_files():
    """
    Saves the generated template as JSON file.
    """
    with open(args.output_template, "w") as f:
        f.write(json.dumps(template, indent=4))


def main():
    """
    Main execution function that orchestrates the processing of biomedical concepts, datasets,
    standards, and saves the output files.
    """
    process_bc()
    build_vlm_lookup()
    update_datasets_dict()
    populate_study_elements()
    process_datasets()
    add_standards()
    save_output_files()


if __name__ == "__main__":
    main()
