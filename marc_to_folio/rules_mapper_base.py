import json
import logging

from pymarc.field import Field
from marc_to_folio.helper import Helper
from marc_to_folio.conditions import Conditions
from marc_to_folio.report_blurbs import blurbs
import time
from folioclient import FolioClient
from typing import Dict, List
import pymarc
import copy
import os
import sys

from textwrap import wrap

import requests


class RulesMapperBase:
    def __init__(self, folio_client : FolioClient, conditions=None):
        self.migration_report = {}
        self.mapped_folio_fields = {}
        self.mapped_legacy_fields = {}
        self.start = time.time()
        self.stats = {}
        self.folio_client : FolioClient = folio_client
        self.holdings_json_schema = fetch_holdings_schema()
        self.instance_json_schema = get_instance_schema()
        self.schema = {}
        self.conditions = conditions
        self.item_json_schema = ""
        self.mappings = {}
        logging.info(f"Current user id is {self.folio_client.current_user}")

    def report_legacy_mapping(self, field_name, present, mapped, empty=False):
        if field_name not in self.mapped_legacy_fields:
            self.mapped_legacy_fields[field_name] = [
                int(present),
                int(mapped),
                int(empty),
            ]
        else:
            self.mapped_legacy_fields[field_name][0] += int(present)
            self.mapped_legacy_fields[field_name][1] += int(mapped)
            self.mapped_legacy_fields[field_name][2] += int(empty)

    def report_folio_mapping(self, field_name, was_mapped, was_empty=False):
        if field_name not in self.mapped_folio_fields:
            self.mapped_folio_fields[field_name] = [int(was_mapped), int(was_empty)]
        else:
            self.mapped_folio_fields[field_name][0] += int(was_mapped)
            self.mapped_folio_fields[field_name][1] += int(was_empty)

    def print_mapping_report(self, report_file):

        total_records = self.stats["Number of records in file(s)"]
        header = "Mapped FOLIO fields"

        report_file.write(f"\n## {header}\n")
        report_file.write(f"{blurbs[header]}\n")

        d_sorted = {
            k: self.mapped_folio_fields[k] for k in sorted(self.mapped_folio_fields)
        }
        report_file.write(
            f"<details><summary>Click to expand field report</summary>     \n\n"
        )
        report_file.write(f"FOLIO Field | Mapped | Empty | Unmapped  \n")
        report_file.write("--- | --- | --- | ---:  \n")
        for k, v in d_sorted.items():
            unmapped = total_records - v[0]
            mapped = v[0] - v[1]
            mp = mapped / total_records if total_records else 0
            mapped_per = "{:.0%}".format(mp if mp > 0 else 0)
            report_file.write(
                f"{k} | {mapped if mapped > 0 else 0} ({mapped_per}) | {v[1]} | {unmapped}  \n"
            )
        report_file.write("</details>   \n")

        # Legacy fields (like marc)
        header = "Mapped Legacy fields"
        report_file.write(f"\n## {header}\n")
        report_file.write(f"{blurbs[header]}\n")

        d_sorted = {
            k: self.mapped_legacy_fields[k] for k in sorted(self.mapped_legacy_fields)
        }
        report_file.write(
            f"<details><summary>Click to expand field report</summary>     \n\n"
        )
        report_file.write(f"Legacy Field | Present | Mapped | Empty | Unmapped  \n")
        report_file.write("--- | --- | --- | --- | ---:  \n")
        for k, v in d_sorted.items():
            present = v[0]
            present_per = "{:.1%}".format(
                present / total_records if total_records else 0
            )
            unmapped = present - v[1]
            mapped = v[1]
            mp = mapped / total_records if total_records else 0
            mapped_per = "{:.0%}".format(mp if mp > 0 else 0)
            report_file.write(
                f"{k} | {present if present > 0 else 0} ({present_per}) | {mapped if mapped > 0 else 0} ({mapped_per}) | {v[1]} | {unmapped}  \n"
            )
        report_file.write("</details>   \n")

    def add_to_migration_report(self, header, measure_to_add):
        """Add section header and values to migration report."""

        if header not in self.migration_report:
            self.migration_report[header] = {}
        if measure_to_add not in self.migration_report[header]:
            self.migration_report[header][measure_to_add] = 1
        else:
            self.migration_report[header][measure_to_add] += 1

    def write_migration_report(self, report_file):
        """Writes the migrstion report, including section headers, section blurbs, and values."""
        report_file.write(f"{blurbs['Introduction']}\n")

        for a in self.migration_report:
            report_file.write(f"   \n")
            report_file.write(f"## {a}    \n")
            try:
                report_file.write(f"{blurbs[a]}    \n")
            except KeyError as key_error:
                logging.error(
                    f"Uhoh. Please add this one to report_blurbs.py: {key_error}"
                )

            report_file.write(
                f"<details><summary>Click to expand all {len(self.migration_report[a])} things</summary>     \n"
            )
            report_file.write(f"   \n")
            report_file.write(f"Measure | Count   \n")
            report_file.write(f"--- | ---:   \n")
            b = self.migration_report[a]
            sortedlist = [(k, b[k]) for k in sorted(b, key=as_str)]
            for b in sortedlist:
                report_file.write(f"{b[0]} | {b[1]}   \n")
            report_file.write("</details>   \n")

    def print_progress(self):
        self.add_stats(self.stats, "Number of records in file(s)")
        i = self.stats["Number of records in file(s)"]
        if i % 1000 == 0:
            elapsed = i / (time.time() - self.start)
            elapsed_formatted = "{0:.4g}".format(elapsed)
            logging.info(f"{elapsed_formatted} records/sec.\t\t{i:,} records processed")

    def print_dict_to_md_table(self, my_dict, report_file, h1="Measure", h2="Number"):
        # TODO: Move to interface or parent class
        d_sorted = {k: my_dict[k] for k in sorted(my_dict)}
        report_file.write(f"{h1} | {h2}   \n")
        report_file.write(f"--- | ---:   \n")
        for k, v in d_sorted.items():
            report_file.write(f"{k} | {v:,}   \n")

    def add_stats(self, stats, a):
        if a not in stats:
            stats[a] = 1
        else:
            stats[a] += 1

    def count_unmapped_fields(self, schema, folio_object):
        schema_properties = schema["properties"].keys()
        unmatched_properties = (
            p for p in schema_properties if p not in folio_object.keys()
        )
        for p in unmatched_properties:
            self.report_folio_mapping(p, False, False)

    def count_mapped_fields(self, folio_object):
        schema_properties = self.schema["properties"].keys()
        matched_properties = (p for p in schema_properties if p in folio_object.keys())
        for p in matched_properties:
            self.report_folio_mapping(p, True, False)
        """keys_to_delete = []
        for key, value in folio_object.items():
            if isinstance(value, str):
                self.report_folio_mapping(key, True, not value)
                if not value:
                    keys_to_delete.append(key)
            elif isinstance(value, bool):
                self.report_folio_mapping(key, True, not value)
                if not value:
                    keys_to_delete.append(key)
            elif isinstance(value, list):
                self.report_folio_mapping(key, True, not any(value))
                if not any(value):
                    keys_to_delete.append(key)
            elif isinstance(value, dict):
                self.report_folio_mapping(key, True, not any(value))
                if not any(value):
                    keys_to_delete.append(key)
            else:
                self.report_folio_mapping(key, True, not any(value))
                logging.info(type(value))
                # logging.info(type(value))
        for mykey in keys_to_delete:
            del folio_object[mykey]"""

    def dedupe_rec(self, rec):
        # remove duplicates
        for key, value in rec.items():
            if isinstance(value, list):
                res = []
                for v in value:
                    if v not in res:
                        res.append(v)
                rec[key] = res

    def map_field_according_to_mapping(self, marc_field: pymarc.Field, mappings, rec):
        for mapping in mappings:
            if "entity" not in mapping:
                target = mapping["target"]
                if has_conditions(mapping):
                    values = self.apply_rules(marc_field, mapping)
                    # TODO: add condition to customize this...
                    if marc_field.tag == "655":
                        values[0] = f"Genre: {values[0]}"
                    self.add_value_to_target(rec, target, values)
                elif has_value_to_add(mapping):
                    value = mapping["rules"][0]["value"]
                    # Stupid construct to avoid bool("false") == True
                    if value == "true":
                        self.add_value_to_target(rec, target, [True])
                    elif value == "false":
                        self.add_value_to_target(rec, target, [False])
                    else:
                        self.add_value_to_target(rec, target, [value])
                else:
                    # Adding stuff without rules/Conditions.
                    # Might need more complex mapping for arrays etc
                    if any(mapping["subfield"]):
                        value = " ".join(marc_field.get_subfields(*mapping["subfield"]))
                    else:
                        value = marc_field.format_field() if marc_field else ""
                    self.add_value_to_target(rec, target, [value])
            else:
                e_per_subfield = mapping.get("entityPerRepeatedSubfield", False)
                self.handle_entity_mapping(
                    marc_field, mapping["entity"], rec, e_per_subfield
                )

    def apply_rules(self, marc_field: pymarc.Field, mapping):
        values = []
        value = ""
        if has_conditions(mapping):
            c_type_def = mapping["rules"][0]["conditions"][0]["type"].split(",")
            condition_types = [x.strip() for x in c_type_def]
            parameter = mapping["rules"][0]["conditions"][0].get("parameter", {})
            # logging.info(f'conditions {condition_types}')
            if mapping.get("applyRulesOnConcatenatedData", ""):
                value = " ".join(marc_field.get_subfields(*mapping["subfield"]))
                value = self.apply_rule(value, condition_types, marc_field, parameter)
            else:
                if mapping.get("subfield", []):
                    if mapping.get("ignoreSubsequentFields", False):
                        sfs = []
                        for sf in mapping["subfield"]:
                            next_subfield = next(iter(marc_field.get_subfields(sf)), "")
                            sfs.append(next_subfield)
                        value = " ".join(
                            [
                                self.apply_rule(
                                    x, condition_types, marc_field, parameter
                                )
                                for x in sfs
                            ]
                        )
                    else:
                        subfields = marc_field.get_subfields(*mapping["subfield"])
                        x = [
                            self.apply_rule(x, condition_types, marc_field, parameter)
                            for x in subfields
                        ]
                        value = " ".join(set(x))
                else:
                    value1 = marc_field.format_field() if marc_field else ""
                    value = self.apply_rule(
                        value1, condition_types, marc_field, parameter
                    )
        elif has_value_to_add(mapping):
            value = mapping["rules"][0]["value"]
            if value == "false":
                return [False]
            elif value == "true":
                return [True]
            else:
                return [value]
        elif not mapping.get("rules", []) or not mapping["rules"][0].get(
            "conditions", []
        ):
            value = " ".join(marc_field.get_subfields(*mapping["subfield"]))
        if mapping.get("subFieldSplit", ""):
            values = wrap(value, 3)
        else:
            values = [value]
        return values

    def add_value_to_target(self, rec, target_string, value):
        if value:
            targets = target_string.split(".")
            if len(targets) == 1:
                self.add_value_to_first_level_target(rec, target_string, value)

            else:
                schema_parent = None
                parent = None
                schema_properties = self.schema["properties"]
                sc_prop = schema_properties
                # prop = copy.deepcopy(rec)
                for target in targets:  # Iterate over names in hierarcy
                    if target in sc_prop:  # property is on this level
                        sc_prop = sc_prop[target]  # set current property
                    else:  # next level. take the properties from the items
                        sc_prop = schema_parent["items"]["properties"][target]
                    if (
                        target not in rec and not schema_parent
                    ):  # have we added this already?
                        if is_array_of_strings(sc_prop):
                            rec[target] = []
                            # break
                            # prop[target].append({})
                        elif is_array_of_objects(sc_prop):
                            rec[target] = [{}]
                            # break
                        elif (
                            schema_parent
                            and is_array_of_objects(schema_parent)
                            and sc_prop.get("type", "string") == "string"
                        ):
                            logging.error("This should be unreachable code")
                            raise Exception("This should be unreachable code")
                            # logging.error(f"break! {target} {prop} {value}")
                            if len(rec[parent][-1]) > 0:
                                rec[parent][-1][target] = value[0]
                            else:
                                rec[parent][-1] = {target: value[0]}
                            # logging.info(parent)
                            # break
                        else:
                            if schema_parent["type"] == "array":
                                # prop[target] = {}
                                # parent.append(prop[target])
                                parent.append({})
                            else:
                                raise Exception(
                                    f"Edge! {target_string} {schema_properties[target_string]}"
                                )
                    else:  # We already have stuff in here
                        if is_array_of_objects(sc_prop) and len(rec[target][-1]) == len(
                            sc_prop["items"]["properties"]
                        ):
                            rec[target].append({})
                        elif schema_parent and target in rec[parent][-1]:
                            rec[parent].append({})
                            if len(rec[parent][-1]) > 0:
                                rec[parent][-1][target] = value[0]
                            else:
                                rec[parent][-1] = {target: value[0]}
                        elif (
                            schema_parent
                            and is_array_of_objects(schema_parent)
                            and sc_prop.get("type", "string") == "string"
                        ):
                            # logging.debug(f"break! {target} {prop} {value}")
                            if len(rec[parent][-1]) > 0:
                                rec[parent][-1][target] = value[0]
                                logging.debug(rec[parent])
                            else:
                                rec[parent][-1] = {target: value[0]}
                                logging.debug(rec[parent])
                        # break

                    # if target == targets[-1]:
                    # logging.debug(f"HIT {target} {value[0]}")
                    # prop[target] = value[0]
                    # prop = rec[target]
                    schema_parent = sc_prop
                    parent = target

    def add_value_to_first_level_target(self, rec, target_string, value):
        logging.debug(f"{target_string} {value} {rec}")
        sch = self.schema["properties"]

        if not target_string or target_string not in sch:
            raise Exception(
                f"Target string {target_string} not in Schema! Target type: {sch.get(target_string,{}).get('type','')} Value: {value}"
            )

        target_field = sch.get(target_string, {})
        if (
            target_field.get("type", "") == "array"
            and target_field.get("items", {}).get("type", "") == "string"
        ):

            if target_string not in rec:
                rec[target_string] = value
            else:
                rec[target_string].extend(value)

        elif target_field.get("type", "") == "string":
            rec[target_string] = value[0]
        else:
            raise Exception(
                f"Edge! Target string: {target_string} Target type: {sch.get(target_string,{}).get('type','')} Value: {value}"
            )

    def create_entity(self, entity_mappings, marc_field, entity_parent_key):
        entity = {}
        for entity_mapping in entity_mappings:
            k = entity_mapping["target"].split(".")[-1]
            values = self.apply_rules(marc_field, entity_mapping)
            if values:
                if entity_parent_key == k:
                    entity = values[0]
                else:
                    entity[k] = values[0]
        return entity

    def handle_entity_mapping(
        self, marc_field : Field, entity_mapping, rec, e_per_subfield
    ):
        e_parent = entity_mapping[0]["target"].split(".")[0]
        if e_per_subfield:
            for sf_tuple in grouped(marc_field.subfields, 2):
                temp_field = Field(
                    tag=marc_field.tag,
                    indicators=marc_field.indicators,
                    subfields=[sf_tuple[0], sf_tuple[1]],
                )
                entity = self.create_entity(entity_mapping, temp_field, e_parent)
                if type(entity) is dict and any(entity.values()):
                    self.add_entity_to_record(entity, e_parent, rec)
                elif type(entity) is list and any(entity):
                    self.add_entity_to_record(entity, e_parent, rec)
        else:
            entity = self.create_entity(entity_mapping, marc_field, e_parent)
            if e_parent in ["precedingTitles", "succeedingTitles"]:
                self.add_to_migration_report(
                    "Preceding and Succeding titles", f"{e_parent} created"
                )
                logging.log(25, json.dumps({e_parent: entity}))
            elif (
                all(
                    v
                    for k, v in entity.items()
                    if k
                    not in [
                        "staffOnly",
                        "primary",
                        "isbnValue",
                        "issnValue",
                    ]
                )
                or e_parent in ["electronicAccess", "publication"]
                or (
                    e_parent.startswith("holdingsStatements")
                    and any(v for k, v in entity.items())
                )
            ):
                self.add_entity_to_record(entity, e_parent, rec)
            else:
                sfs = " - ".join(f[0] for f in marc_field)

                pattern = " - ".join(f"{k}:{bool(v)}" for k, v in entity.items())
                self.add_to_migration_report(
                    "Incomplete entity mapping adding entity",
                    f"{marc_field.tag} {sfs} --- {e_parent} {pattern}  ",
                )
                # Experimental
                # self.add_entity_to_record(entity, e_parent, rec)

    def apply_rule(self, value, condition_types, marc_field, parameter):
        v = value
        for condition_type in condition_types:
            v = self.conditions.get_condition(condition_type, v, parameter, marc_field)
        return v

    def add_entity_to_record(self, entity, entity_parent_key, rec):
        sch = self.schema["properties"]
        if sch[entity_parent_key]["type"] == "array":
            if entity_parent_key not in rec:
                rec[entity_parent_key] = [entity]
            else:
                rec[entity_parent_key].append(entity)
        else:
            rec[entity_parent_key] = entity


def as_str(s):
    try:
        return str(s), ""
    except ValueError:
        return "", s


def fetch_holdings_schema():
    logging.info("Fetching HoldingsRecord schema...")
    holdings_record_schema = Helper.get_latest_from_github(
        "folio-org", "mod-inventory-storage", "ramls/holdingsrecord.json"
    )
    logging.info("done")
    return holdings_record_schema


def get_instance_schema():
    logging.info("Fetching Instance schema...")
    instance_schema = Helper.get_latest_from_github(
        "folio-org", "mod-inventory-storage", "ramls/instance.json"
    )
    logging.info("done")
    return instance_schema


def has_conditions(mapping):
    return mapping.get("rules", []) and mapping["rules"][0].get("conditions", [])


def has_value_to_add(mapping):
    return mapping.get("rules", []) and mapping["rules"][0].get("value", "")


def is_array_of_strings(schema_property):
    sc_prop_type = schema_property.get("type", "string")
    return sc_prop_type == "array" and schema_property["items"]["type"] == "string"


def is_array_of_objects(schema_property):
    sc_prop_type = schema_property.get("type", "string")
    return sc_prop_type == "array" and schema_property["items"]["type"] == "object"


def grouped(iterable, n):
    "s -> (s0,s1,s2,...sn-1), (sn,sn+1,sn+2,...s2n-1), (s2n,s2n+1,s2n+2,...s3n-1), ..."
    return zip(*[iter(iterable)] * n)
