"""The default mapper, responsible for parsing MARC21 records acording to the
FOLIO community specifications"""
import logging
import time
import uuid
from typing import List

import pymarc
from folio_uuid.folio_namespaces import FOLIONamespaces
from folio_uuid.folio_uuid import FolioUUID
from folioclient import FolioClient
from pymarc import Record

from folio_migration_tools.custom_exceptions import TransformationProcessError
from folio_migration_tools.library_configuration import FileDefinition
from folio_migration_tools.library_configuration import IlsFlavour
from folio_migration_tools.library_configuration import LibraryConfiguration
from folio_migration_tools.marc_rules_transformation.conditions import Conditions
from folio_migration_tools.marc_rules_transformation.hrid_handler import HRIDHandler
from folio_migration_tools.marc_rules_transformation.rules_mapper_base import (
    RulesMapperBase,
)


class AuthorityMapper(RulesMapperBase):
    """_summary_

    Args:
        RulesMapperBase (_type_): _description_
    """

    def __init__(
        self,
        folio_client,
        library_configuration: LibraryConfiguration,
        task_configuration,
    ):
        super().__init__(
            folio_client,
            library_configuration,
            task_configuration,
            self.get_autority_json_schema(),
            Conditions(folio_client, self, "auth", library_configuration.folio_release),
        )
        self.record_status: dict = {}
        self.id_map: dict = {}
        self.srs_recs: list = []
        self.mapped_folio_fields: dict = {}
        logging.info("Fetching mapping rules from the tenant")
        rules_endpoint = "/mapping-rules/marc-authority"
        self.mappings = self.folio_client.folio_get_single_object(rules_endpoint)
        self.start = time.time()

    def get_legacy_ids(
        self, marc_record: Record, ils_flavour: IlsFlavour, index_or_legacy_id: str
    ) -> List[str]:
        if ils_flavour in {IlsFlavour.sierra, IlsFlavour.millennium}:
            raise TransformationProcessError("", f"ILS {ils_flavour} not configured")
        elif ils_flavour == IlsFlavour.tag907y:
            return self.get_bib_id_from_907y(marc_record, index_or_legacy_id)
        elif ils_flavour == IlsFlavour.tagf990a:
            return self.get_bib_id_from_990a(marc_record, index_or_legacy_id)
        elif ils_flavour == IlsFlavour.aleph:
            raise TransformationProcessError("", f"ILS {ils_flavour} not configured")
        elif ils_flavour in {IlsFlavour.voyager, "voyager", IlsFlavour.tag001}:
            return self.get_bib_id_from_001(marc_record, index_or_legacy_id)
        elif ils_flavour == IlsFlavour.koha:
            raise TransformationProcessError("", f"ILS {ils_flavour} not configured")
        elif ils_flavour == IlsFlavour.none:
            return [str(uuid.uuid4())]
        else:
            raise TransformationProcessError("", f"ILS {ils_flavour} not configured")

    def parse_auth(self, legacy_ids, marc_record: Record, file_def: FileDefinition):
        """Parses an auth recod into a FOLIO Authority object
         This is the main function

        Args:
            legacy_ids (_type_): _description_
            marc_record (Record): _description_
            file_def (FileDefinition): _description_

        Returns:
            _type_: _description_
        """
        self.print_progress()
        ignored_subsequent_fields: set = set()
        bad_tags = set(self.task_configuration.tags_to_delete)  # "907"
        folio_authority = self.perform_initial_preparation(marc_record, legacy_ids)
        for marc_field in marc_record:
            self.report_marc_stats(marc_field, bad_tags, legacy_ids, ignored_subsequent_fields)
            if marc_field.tag not in ignored_subsequent_fields:
                self.process_marc_field(
                    folio_authority,
                    marc_field,
                    ignored_subsequent_fields,
                    legacy_ids,
                )

        self.perform_additional_parsing(folio_authority, marc_record, legacy_ids, file_def)
        clean_folio_authority = self.validate_required_properties(
            "-".join(legacy_ids), folio_authority, self.schema, FOLIONamespaces.instances
        )
        self.dedupe_rec(clean_folio_authority)
        marc_record.remove_fields(*list(bad_tags))
        self.report_folio_mapping(clean_folio_authority, self.schema)
        # TODO: trim away multiple whitespace and newlines..
        # TODO: createDate and update date and catalogeddate
        return clean_folio_authority

    def perform_initial_preparation(self, marc_record: pymarc.Record, legacy_ids):
        folio_authority = {
            "metadata": self.folio_client.get_metadata_construct(),
        }
        folio_authority["id"] = str(
            FolioUUID(
                str(self.folio_client.okapi_url),
                FOLIONamespaces.athorities,
                str(legacy_ids[-1]),
            )
        )
        HRIDHandler.handle_035_generation(
            marc_record, legacy_ids, self.migration_report, False, False
        )

        return folio_authority

    def perform_additional_parsing(
        self,
        folio_authority: dict,
        marc_record: Record,
        legacy_ids: List[str],
        file_def: FileDefinition,
    ) -> None:
        """Do stuff not easily captured by the mapping rules

        Args:
            folio_authority (dict): _description_
            marc_record (Record): _description_
            legacy_ids (List[str]): _description_
            file_def (FileDefinition): _description_
        """
        folio_authority["source"] = "MARC"

    def get_autority_json_schema(self, latest_release=True):
        """Fetches the JSON Schema for autorities"""
        return FolioClient.get_latest_from_github(
            "folio-org", "mod-inventory-storage", "/ramls/authorities/authority.json"
        )