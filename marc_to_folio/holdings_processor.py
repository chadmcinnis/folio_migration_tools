""" Class that processes each MARC record """
from marc_to_folio.folder_structure import FolderStructure
from marc_to_folio.custom_exceptions import TransformationCriticalDataError
from marc_to_folio.helper import Helper
from marc_to_folio.rules_mapper_holdings import RulesMapperHoldings
import time
import json
import traceback
import logging
import os
from datetime import datetime as dt
from jsonschema import ValidationError, validate


class HoldingsProcessor:
    """the processor"""

    def __init__(self, mapper, folio_client, folder_structure:FolderStructure, suppress: bool):
        self.folder_structure : FolderStructure = folder_structure
        self.records_count = 0
        self.missing_instance_id_count = 0
        self.mapper : RulesMapperHoldings = mapper
        self.start = time.time()
        self.suppress = suppress
        self.created_objects_file = open(self.folder_structure.created_objects_path, "w+")

    def process_record(self, marc_record):
        """processes a marc holdings record and saves it"""
        try:
            self.records_count += 1
            # Transform the MARC21 to a FOLIO record
            folio_rec = self.mapper.parse_hold(marc_record)
            if not folio_rec.get("instanceId", ""):
                self.missing_instance_id_count += 1
                if self.missing_instance_id_count > 1000:
                    raise Exception(f"More than 1000 missing instance ids. Something is wrong. Last 004: {marc_record['004']}")

            Helper.write_to_file(self.created_objects_file, folio_rec)
            add_stats(self.mapper.stats, "Holdings records written to disk")
            # Print progress
            if self.records_count % 10000 == 0:
                logging.info(self.mapper.stats)
                elapsed = self.records_count / (time.time() - self.start)
                elapsed_formatted = "{0:.4g}".format(elapsed)
                logging.info(f"{elapsed_formatted}\t\t{self.records_count}")
        except TransformationCriticalDataError as data_error:
            add_stats(self.mapper.stats, "Critical data errors")
            add_stats(self.mapper.stats, "Failed records")
            logging.error(data_error)
            remove_from_id_map = getattr(self.mapper, "remove_from_id_map", None)
            if callable(remove_from_id_map):
                self.mapper.remove_from_id_map(marc_record)
        except ValueError as value_error:
            add_stats(self.mapper.stats, "Value errors")
            add_stats(self.mapper.stats, "Failed records")
            logging.debug(marc_record)
            logging.error(value_error)
            remove_from_id_map = getattr(self.mapper, "remove_from_id_map", None)
            if callable(remove_from_id_map):
                self.mapper.remove_from_id_map(marc_record)
        except ValidationError as validation_error:
            add_stats(self.mapper.stats, "Validation errors")
            add_stats(self.mapper.stats, "Failed records")
            logging.error(validation_error)
            remove_from_id_map = getattr(self.mapper, "remove_from_id_map", None)
            if callable(remove_from_id_map):
                self.mapper.remove_from_id_map(marc_record)
        except Exception as inst:
            remove_from_id_map = getattr(self.mapper, "remove_from_id_map", None)
            if callable(remove_from_id_map):
                self.mapper.remove_from_id_map(marc_record)
            traceback.print_exc()
            logging.error(type(inst))
            logging.error(inst.args)
            logging.error(inst)
            logging.error(marc_record)
            raise inst

    def wrap_up(self):
        """Finalizes the mapping by writing things out."""
        self.created_objects_file.close()
        id_map = self.mapper.holdings_id_map
        logging.warning(
            f"Saving map of {len(id_map)} old and new IDs to {self.folder_structure.holdings_id_map_path}"
        )
        with open(self.folder_structure.holdings_id_map_path, "w+") as id_map_file:
            json.dump(id_map, id_map_file)
        logging.warning(f"{self.records_count} records processed")
        with open(self.folder_structure.migration_reports_file, "w+") as report_file:
            report_file.write(f"# MFHD records transformation results   \n")
            report_file.write(f"Time Finished: {dt.isoformat(dt.utcnow())}   \n")
            report_file.write(f"## MFHD records transformation counters   \n")
            self.mapper.print_dict_to_md_table(
                self.mapper.stats, report_file, "Measure","Count",
            )
            self.mapper.write_migration_report(report_file)
            self.mapper.print_mapping_report(report_file)
            
        logging.info(f"Done. Transformation report written to {report_file}")


def add_stats(stats, a):
    # TODO: Move to interface or parent class
    if a not in stats:
        stats[a] = 1
    else:
        stats[a] += 1
