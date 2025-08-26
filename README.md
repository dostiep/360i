# 360i

* dataset-json.py : From a Define.xml file, create Dataset-JSON datasets shells using both Extract-list-DS.xsl and Dataset-JSON.xsl stylesheets. Compliance to Dataset-JSON is done using JSON schema file dataset.schema.json.

* Shells.sas : From a Define.xml file, create Dataset-JSON datasets shells using both Extract-list-DS.xsl and Dataset-JSON.xsl stylesheets. No compliance to Dataset-JSON is performed.

* Extract-list-DS.xsl : Stylesheet that creates a list of all datasets names separated by a comma. Used to loop through the creation of Dataset-JSON shells.

* Dataset-JSON.xsl : Stylesheet that creates empty datasets shells compliant to Dataset-JSON model based on a Define.xml.

* dataset.schema.json : JSON schema file to validate Dataset-JSON datasets files.

* Define-Template.py : From a USDM JSON study definition, create the Define-Template.json file which can be used to create the SDTM Shell Datasets.
    * Usage: python Define-Template.py --usdm_file <path_to_usdm_json_file>
