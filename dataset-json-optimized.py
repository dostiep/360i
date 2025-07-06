#!/usr/bin/env python3
"""
Optimized Dataset-JSON Generator

This script processes Define.xml files to create Dataset-JSON shells
with significant performance optimizations and improved error handling.
"""

import json
import time
import sys
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime
from contextlib import contextmanager

from saxonche import PySaxonProcessor
from jsonschema import validate, ValidationError


class DatasetJSONGenerator:
    """Optimized Dataset-JSON generator with performance improvements."""
    
    def __init__(self, define_file: str = "define-2-1-ADaM.xml", 
                 schema_file: str = "dataset.schema.json"):
        self.define_file = define_file
        self.schema_file = schema_file
        self.processor = PySaxonProcessor(license=False)
        
        # Pre-compiled resources (optimization: compile once, use many times)
        self._schema: Optional[Dict[Any, Any]] = None
        self._parsed_xml = None
        self._extract_stylesheet = None
        self._dataset_stylesheet = None
        
        # Performance tracking
        self.stats = {
            'total_time': 0,
            'datasets_processed': 0,
            'validation_errors': 0,
            'files_created': 0
        }
    
    @contextmanager
    def timer(self, operation: str):
        """Context manager for timing operations."""
        start_time = time.time()
        try:
            yield
        finally:
            elapsed = time.time() - start_time
            print(f"{operation}: {elapsed:.3f}s")
    
    def _load_schema(self) -> Dict[Any, Any]:
        """Load and cache JSON schema (optimization: load once)."""
        if self._schema is None:
            try:
                with open(self.schema_file, 'r', encoding='utf-8') as f:
                    self._schema = json.load(f)
                print(f"✓ Loaded JSON schema: {self.schema_file}")
            except (FileNotFoundError, json.JSONDecodeError) as e:
                raise RuntimeError(f"Failed to load schema {self.schema_file}: {e}")
        return self._schema
    
    def _parse_xml(self):
        """Parse XML file once and cache (optimization: parse once)."""
        if self._parsed_xml is None:
            try:
                self._parsed_xml = self.processor.parse_xml(xml_file_name=self.define_file)
                print(f"✓ Parsed XML file: {self.define_file}")
            except Exception as e:
                raise RuntimeError(f"Failed to parse XML {self.define_file}: {e}")
        return self._parsed_xml
    
    def _compile_stylesheets(self):
        """Compile XSLT stylesheets once and cache (optimization: compile once)."""
        if self._extract_stylesheet is None:
            try:
                self._extract_stylesheet = self.processor.new_xslt30_processor().compile_stylesheet(
                    stylesheet_file="Extract-list-DS.xsl"
                )
                print("✓ Compiled Extract-list-DS.xsl stylesheet")
            except Exception as e:
                raise RuntimeError(f"Failed to compile Extract-list-DS.xsl: {e}")
        
        if self._dataset_stylesheet is None:
            try:
                self._dataset_stylesheet = self.processor.new_xslt30_processor().compile_stylesheet(
                    stylesheet_file="Dataset-JSON.xsl"
                )
                print("✓ Compiled Dataset-JSON.xsl stylesheet")
            except Exception as e:
                raise RuntimeError(f"Failed to compile Dataset-JSON.xsl: {e}")
    
    def extract_dataset_names(self) -> List[str]:
        """Extract dataset names from Define.xml."""
        with self.timer("Dataset extraction"):
            self._compile_stylesheets()
            parsed_xml = self._parse_xml()
            
            result = self._extract_stylesheet.transform_to_string(xdm_node=parsed_xml)
            dataset_names = [name.strip() for name in result.split(",") if name.strip()]
            
            print(f"✓ Extracted {len(dataset_names)} datasets: {', '.join(dataset_names)}")
            return dataset_names
    
    def create_dataset_json(self, dataset_name: str, creation_time: str) -> Optional[Dict[Any, Any]]:
        """Create Dataset-JSON for a single dataset."""
        try:
            # Set parameters for this specific dataset
            self._dataset_stylesheet.set_parameter("dsName", 
                                                 self.processor.make_string_value(dataset_name))
            self._dataset_stylesheet.set_parameter("datasetJSONCreationDateTime", 
                                                 self.processor.make_string_value(creation_time))
            
            # Transform to JSON string
            json_string = self._dataset_stylesheet.transform_to_string(xdm_node=self._parsed_xml)
            
            # Parse JSON
            return json.loads(json_string)
            
        except (json.JSONDecodeError, Exception) as e:
            print(f"✗ Failed to create JSON for dataset {dataset_name}: {e}")
            return None
    
    def validate_dataset(self, json_data: Dict[Any, Any], dataset_name: str) -> bool:
        """Validate dataset against JSON schema."""
        try:
            schema = self._load_schema()
            validate(json_data, schema)
            return True
        except ValidationError as e:
            print(f"✗ Validation failed for {dataset_name}: {e.message}")
            self.stats['validation_errors'] += 1
            return False
    
    def save_dataset(self, json_data: Dict[Any, Any], dataset_name: str) -> bool:
        """Save dataset to JSON file."""
        try:
            output_file = f"{dataset_name}.json"
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(json_data, f, indent=4, ensure_ascii=False)
            
            file_size = Path(output_file).stat().st_size
            print(f"✓ Created {output_file} ({file_size:,} bytes)")
            self.stats['files_created'] += 1
            return True
            
        except Exception as e:
            print(f"✗ Failed to save {dataset_name}.json: {e}")
            return False
    
    def process_all_datasets(self):
        """Main processing function with optimizations."""
        start_time = time.time()
        
        try:
            print("🚀 Starting optimized Dataset-JSON generation...")
            print("=" * 60)
            
            # Pre-load and compile everything once (major optimization)
            with self.timer("Initialization"):
                self._load_schema()
                self._parse_xml()
                self._compile_stylesheets()
            
            # Extract dataset names
            dataset_names = self.extract_dataset_names()
            
            if not dataset_names:
                print("⚠️  No datasets found in Define.xml")
                return
            
            # Generate creation timestamp once for all datasets
            creation_time = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')
            
            print("\n📊 Processing datasets...")
            print("-" * 40)
            
            # Process each dataset
            for i, dataset_name in enumerate(dataset_names, 1):
                print(f"\n[{i}/{len(dataset_names)}] Processing: {dataset_name}")
                
                with self.timer(f"  Dataset {dataset_name}"):
                    # Create JSON data
                    json_data = self.create_dataset_json(dataset_name, creation_time)
                    if json_data is None:
                        continue
                    
                    # Validate against schema
                    if not self.validate_dataset(json_data, dataset_name):
                        continue
                    
                    # Save to file
                    if self.save_dataset(json_data, dataset_name):
                        self.stats['datasets_processed'] += 1
            
            # Final statistics
            self.stats['total_time'] = time.time() - start_time
            self._print_summary()
            
        except Exception as e:
            print(f"💥 Fatal error: {e}")
            sys.exit(1)
    
    def _print_summary(self):
        """Print processing summary and performance statistics."""
        print("\n" + "=" * 60)
        print("📈 PROCESSING SUMMARY")
        print("=" * 60)
        print(f"✅ Total datasets processed: {self.stats['datasets_processed']}")
        print(f"📁 Files created: {self.stats['files_created']}")
        print(f"⚠️  Validation errors: {self.stats['validation_errors']}")
        print(f"⏱️  Total time: {self.stats['total_time']:.3f}s")
        
        if self.stats['datasets_processed'] > 0:
            avg_time = self.stats['total_time'] / self.stats['datasets_processed']
            print(f"📊 Average time per dataset: {avg_time:.3f}s")
        
        print("=" * 60)


def main():
    """Main entry point."""
    # Check if Define.xml file exists
    define_file = "define-2-1-ADaM.xml"
    if not Path(define_file).exists():
        print(f"❌ Error: {define_file} not found in current directory")
        print("Please ensure the Define.xml file is present.")
        sys.exit(1)
    
    # Check if required stylesheets exist
    required_files = ["Extract-list-DS.xsl", "Dataset-JSON.xsl", "dataset.schema.json"]
    missing_files = [f for f in required_files if not Path(f).exists()]
    
    if missing_files:
        print(f"❌ Error: Missing required files: {', '.join(missing_files)}")
        sys.exit(1)
    
    # Run the optimized generator
    generator = DatasetJSONGenerator(define_file)
    generator.process_all_datasets()


if __name__ == "__main__":
    main()