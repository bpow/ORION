import os
import hashlib
import argparse
import pandas as pd
import logging
import mysql.connector
import re
import random
import requests

from Common.loader_interface import SourceDataLoader
from Common.kgxmodel import kgxnode, kgxedge
from Common.utils import LoggingUtil, GetData


##############
# Class: FooDB loader
#
# By: Phil Owen
# Date: 8/11/2020
# Desc: Class that loads the PHAROS data and creates KGX files for importing into a Neo4j graph.
#       Note that this parser uses a MySQL database that should be started prior to launching the parse.
#       The database (TCRDv6.7.0.sql.gz recent as of 20120/21/9) is ~3.9gb in size.
##############
class PHAROSLoader(SourceDataLoader):
    GENE_TO_DISEASE: str = """select distinct x.value, d.did, d.name, p.sym, d.dtype
                                from disease d 
                                join xref x on x.protein_id = d.protein_id 
                                join protein p on p.id=x.protein_id
                                where x.xtype = 'HGNC' 
                                and d.dtype <> 'Expression Atlas'
                                and d.did not like 'NCBIGene%' 
                                and d.did not like 'AmyCo%'
                                and d.did not like 'ENSP%'"""

    GENE_TO_CMPD_ACTIVITY: str = """SELECT DISTINCT x.value, ca.cmpd_name_in_src as drug, ca.cmpd_id_in_src as cid, catype AS id_src,
                                ca.act_value AS affinity, ca.act_type as affinity_parameter, ca.act_type AS pred, p.sym,
                                ca.pubmed_ids AS pubmed_ids, '' AS dtype
                                FROM xref x
                                JOIN cmpd_activity ca on x.protein_id = ca.target_id
                                JOIN protein p on p.id=x.protein_id
                                WHERE x.xtype='HGNC' and ca.cmpd_name_in_src is not null and ca.cmpd_name_in_src <> 'NA' and ca.cmpd_name_in_src not like 'US%'"""

    GENE_TO_DRUG_ACTIVITY: str = """SELECT DISTINCT x.value, da.drug, da.cmpd_chemblid AS cid, 'ChEMBL' AS id_src, p.sym,
                                da.act_value AS affinity, da.act_type AS affinity_parameter, da.action_type AS pred, '' AS dtype
                                FROM xref x
                                JOIN drug_activity da on x.protein_id = da.target_id
                                JOIN protein p on p.id=x.protein_id
                                WHERE da.cmpd_chemblid IS NOT NULL
                                AND x.xtype='HGNC'"""

    def __init__(self, test_mode: bool = False):
        """
        constructor
        :param test_mode - sets the run into test mode
        """
        # call the super
        super(SourceDataLoader, self).__init__()

        # set global variables
        self.data_path = os.environ['DATA_SERVICES_STORAGE']
        self.data_file = 'latest.sql'
        self.test_mode = test_mode
        self.source_id = 'PHAROS'
        self.source_db = 'Druggable Genome initiative database'
        self.provenance_id = 'infores:pharos'

        # for tracking counts
        self.total_nodes: int = 0
        self.total_edges: int = 0

        # the final output lists of nodes and edges
        self.final_node_list: list = []
        self.final_edge_list: list = []

        # create a logger
        self.logger = LoggingUtil.init_logging("Data_services.PHAROSLoader", level=logging.INFO, line_format='medium', log_file_path=os.environ['DATA_SERVICES_LOGS'])

        # DB connection, lazy instantiation
        self.db = None

    def get_latest_source_version(self) -> str:
        """
        gets the version of the data

        :return: the version of the data
        """
        url = 'http://juniper.health.unm.edu/tcrd/download/latest.README'
        response = requests.get(url)
        version = response.text.splitlines()[0]
        self.logger.info(version)
        return version

    def get_data(self):
        """
        Gets the PHAROS (https://pharos.nih.gov/) data from https://juniper.health.unm.edu/tcrd/download/

        """
        return True

        # and get a reference to the data gatherer
        gd: GetData = GetData(self.logger.level)

        # get all the files noted above
        file_count: int = gd.get_pharos_http_file(self.data_path, self.data_file)

        # abort if we didnt get the file
        if file_count != 1:
            self.logger.error(f'PHAROSLoader - The PHAROS data file was not retrieved.')
            raise Exception('PHAROSLoader - The PHAROS data file was not retrieved.')
        else:
            return True

        # TODO load the datafile into the database

    def parse_data(self) -> dict:
        """
        Parses the PHAROS data to create KGX files.

        :return: parsed meta data results
        """
        # storage for the node list
        node_list: list = []

        final_record_count: int = 0
        final_skipped_count: int = 0

        # get the nodes and edges for each dataset
        node_list, records, skipped = self.parse_gene_to_disease(node_list)
        final_record_count += records
        final_skipped_count += skipped

        node_list, records, skipped = self.parse_gene_to_drug_activity(node_list)
        final_record_count += records
        final_skipped_count += skipped

        node_list, records, skipped = self.parse_gene_to_cmpd_activity(node_list)
        final_record_count += records
        final_skipped_count += skipped

        # is there anything to do
        if len(node_list) > 0:
            self.logger.debug('Creating nodes and edges.')

            # create a data frame with the node list
            df: pd.DataFrame = pd.DataFrame(node_list, columns=['grp', 'node_num', 'id', 'name', 'category', 'equivalent_identifiers', 'predicate', 'relation', 'edge_label', 'pmids', 'affinity', 'affinity_parameter', 'provenance'])

            # get the list of unique nodes and edges
            self.get_nodes_and_edges(df)

            self.logger.debug(f'{len(self.final_node_list)} nodes found, {len(self.final_edge_list)} edges found.')
        else:
            self.logger.warning(f'No records found.')

        # load up the metadata
        load_metadata = {
            'num_source_lines': final_record_count,
            'unusable_source_lines': final_skipped_count
        }

        # return the metadata to the caller
        return load_metadata

    def parse_gene_to_disease(self, node_list: list) -> (list, int, int):
        """
        gets gene to disease records from the pharos DB and creates nodes
        :param node_list: list, the node list to append this data to
        :return: list, the node list and record counters
        """
        # init the record counters
        record_counter: int = 0
        skipped_record_counter: int = 0

        # get the data
        gene_to_disease: dict = self.execute_pharos_sql(self.GENE_TO_DISEASE)

        # create a regex pattern to find UML nodes
        pattern = re.compile('^C\d+$')  # pattern for umls local id

        # for each item in the list
        for item in gene_to_disease:
            # increment the counter
            record_counter += 1

            # get the pertinent info from the record
            gene = item['value']
            did = item['did']
            name = item['name']
            gene_sym = item['sym']
            provenance = item['dtype']

            # move along, no disease id
            if did is None:
                # increment the counter
                skipped_record_counter += 1

                continue
            # if this is a UML node, create the curie
            elif pattern.match(did):
                did = f"UMLS:{did}"
            # if this is a orphanet node, create the curie
            elif did.startswith('Orphanet:'):
                dparts = did.split(':')
                did = 'ORPHANET:' + dparts[1]

            # create the group id
            grp: str = gene + 'WD:P2293' + did + f'{random.random()}'
            grp = hashlib.md5(grp.encode("utf-8")).hexdigest()

            # if the drug id is a gene ignore it
            if did == gene:
                self.logger.error(f'similar parse_gene_to_disease()! {did} == {gene}, {item}')
            else:
                # create the gene node and add it to the node list
                node_list.append({'grp': grp, 'node_num': 1, 'id': gene, 'name': gene_sym, 'category': '', 'equivalent_identifiers': ''})

                # create the disease node and add it to the list
                node_list.append({'grp': grp, 'node_num': 2, 'id': did, 'name': name, 'category': '', 'equivalent_identifiers': '', 'predicate': 'biolink:gene_associated_with_condition', 'relation': 'WD:P2293', 'edge_label': 'gene_associated_with_condition', 'pmids': [], 'affinity': 0, 'affinity_parameter': '', 'provenance': provenance})

        # return the node list to the caller
        return node_list, record_counter, skipped_record_counter

    def parse_gene_to_drug_activity(self, node_list: list) -> (list, int, int):
        """
        gets gene to drug activity records from the pharos DB and creates nodes
        :param node_list: list, the node list to append this data to
        :return: list, the node list and record counters
        """
        # init the record counters
        record_counter: int = 0
        skipped_record_counter: int = 0

        # get the data
        gene_to_drug_activity: dict = self.execute_pharos_sql(self.GENE_TO_DRUG_ACTIVITY)

        prefixmap = {'ChEMBL': 'CHEMBL.COMPOUND:CHEMBL', 'Guide to Pharmacology': 'GTOPDB:'}

        # for each item in the list
        for item in gene_to_drug_activity:
            # increment the counter
            record_counter += 1

            name = item['drug']
            gene = item['value']
            gene_sym = item['sym']
            drug_id = f"{prefixmap[item['id_src']]}{item['cid'].replace('CHEMBL', '')}"
            relation, pmids, props, provenance = self.get_edge_props(item)

            # if there were affinity properties use them
            if len(props) == 2:
                affinity = props['affinity']
                affinity_parameter = props['affinity_parameter']
            else:
                affinity = 0
                affinity_parameter = None

            # create the group id
            grp: str = drug_id + relation + gene + f'{random.random()}'
            grp = hashlib.md5(grp.encode("utf-8")).hexdigest()

            # create the disease node and add it to the node list
            node_list.append({'grp': grp, 'node_num': 1, 'id': drug_id, 'name': name, 'category': '', 'equivalent_identifiers': ''})

            # create the gene node and add it to the list
            node_list.append({'grp': grp, 'node_num': 2, 'id': gene, 'name': gene_sym, 'category': '', 'equivalent_identifiers': '', 'predicate': '', 'relation': relation, 'edge_label': '', 'pmids': pmids, 'affinity': affinity, 'affinity_parameter': affinity_parameter, 'provenance': provenance})

        return node_list, record_counter, skipped_record_counter

    def parse_gene_to_cmpd_activity(self, node_list: list) -> (list, int, int):
        """
        gets gene to compound activity records from the pharos DB and creates nodes
        :param node_list: list, the node list to append this data to
        :return: list, the node list and record counters
        """
        # init the record counters
        record_counter: int = 0
        skipped_record_counter: int = 0

        # get the data
        gene_to_cmpd_activity: dict = self.execute_pharos_sql(self.GENE_TO_CMPD_ACTIVITY)

        prefixmap = {'ChEMBL': 'CHEMBL.COMPOUND:CHEMBL', 'Guide to Pharmacology': 'GTOPDB:'}

        # for each item in the list
        for item in gene_to_cmpd_activity:
            # increment the counter
            record_counter += 1

            name = item['drug']
            gene = item['value']
            gene_sym = item['sym']
            cmpd_id = f"{prefixmap[item['id_src']]}{item['cid'].replace('CHEMBL', '')}"
            relation, pmids, props, provenance = self.get_edge_props(item)

            # if there were affinity properties use them
            if len(props) == 2:
                affinity = props['affinity']
                affinity_parameter = props['affinity_parameter']
            else:
                affinity = 0
                affinity_parameter = None

            # create the group id
            grp: str = cmpd_id + relation + gene + f'{random.random()}'
            grp = hashlib.md5(grp.encode("utf-8")).hexdigest()

            # create the gene node and add it to the list
            node_list.append({'grp': grp, 'node_num': 1, 'id': gene, 'name': gene_sym, 'category': '', 'equivalent_identifiers': ''})

            # create the compound node and add it to the node list
            node_list.append({'grp': grp, 'node_num': 2, 'id': cmpd_id, 'name': name, 'category': '', 'equivalent_identifiers': '', 'predicate': '', 'relation': relation, 'edge_label': '', 'pmids': pmids, 'affinity': affinity, 'affinity_parameter': affinity_parameter, 'provenance': provenance})

        return node_list, record_counter, skipped_record_counter

    def get_edge_props(self, result) -> (str, list, dict, str):
        """
        gets the edge properties from the node results

        :param result:
        :return str: relation, list: pmids, dict: props, str: provenance:
        """
        # if there was a predicate make it look pretty
        if result['pred'] is not None and len(result['pred']) > 1:
            rel: str = self.snakify(result['pred']).lower()
        else:
            rel: str = 'interacts_with'

        # save the relation
        relation: str = f'GAMMA:{rel}'

        # if there was provenance data save it
        if result['dtype'] is not None and len(result['dtype']) > 0:
            provenance = result['dtype']
        else:
            # set the defaults
            provenance = None

        # if there were any pubmed ids save them
        if 'pubmed_ids' in result and result['pubmed_ids'] is not None:
            pmids: list = [f'PMID:{r}' for r in result['pubmed_ids'].split('|')]
        else:
            pmids: list = []

        # init the affinity properties dict
        props: dict = {}

        # if there was data save it
        if result['affinity'] is not None:
            props['affinity'] = float(result['affinity'])
            props['affinity_parameter'] = result['affinity_parameter']
        else:
            # set the defaults
            props['affinity'] = float(0)
            props['affinity_parameter'] = ''

        # return to the caller
        return relation, pmids, props, provenance

    @staticmethod
    def snakify(text):
        decomma = '_'.join(text.split(','))
        dedash = '_'.join(decomma.split('-'))
        resu = '_'.join(dedash.split())
        return resu

    def init_pharos_db(self):
        # get a connection to the PHAROS MySQL DB
        host = os.environ.get('PHAROS_HOST', '')
        user = os.environ.get('PHAROS_USER', '')
        password = os.environ.get('PHAROS_PASSWORD', '')
        database = os.environ.get('PHAROS_DATABASE', '')
        self.db = mysql.connector.connect(host=host, user=user, password=password, database=database)

    def execute_pharos_sql(self, sql_query: str) -> dict:
        """
        executes a sql statement

        :param sql_query:
        :return dict of results:
        """
        if not self.db:
            self.init_pharos_db()

        # get a cursor to the db
        cursor = self.db.cursor(dictionary=True, buffered=True)

        # execute the sql
        cursor.execute(sql_query)

        # get all the records
        ret_val: dict = cursor.fetchall()

        # return to the caller
        return ret_val

    def get_nodes_and_edges(self, df: pd.DataFrame):
        """
        gets a list of nodes and edges for the data frame passed.

        :param df: node storage data frame
        :return:
        """

        # separate the data into triplet groups
        df_grp: pd.groupby_generic.DataFrameGroupBy = df.set_index('grp').groupby('grp')

        # iterate through the groups and create the edge records.
        for row_index, rows in df_grp:
            # did we get the correct number of records in the group
            if len(rows) == 2:
                # init variables for each group
                node_1_id: str = ''

                # find the node
                for row in rows.iterrows():
                    # save the node and node id for the edge
                    if row[1].node_num == 1:
                        if row[1]["name"] is not None:
                            # save the id for the edge
                            node_1_id = row[1]['id']

                            # make sure the name doesnt have any odd characters
                            name = ''.join([x if ord(x) < 128 else '?' for x in row[1]["name"]])

                            # save the node
                            new_node = kgxnode(node_1_id, name=name)
                            self.final_node_list.append(new_node)
                            break

                # did we find the root node
                if node_1_id != '':
                    # now for each node
                    for row in rows.iterrows():
                        # save the nodes and the node id for the edge
                        if row[1].node_num != 1:
                            # make sure the name doesnt have any odd characters
                            name = ''.join([x if ord(x) < 128 else '?' for x in row[1]["name"]])

                            # save the node
                            new_node = kgxnode(row[1]['id'], name=name)
                            self.final_node_list.append(new_node)

                            # save the edge
                            edge_props = {"publications": row[1]['pmids'], "affinity": row[1]['affinity'], "affinity_parameter":  row[1]['affinity_parameter']}
                            new_edge = kgxedge(subject_id=node_1_id,
                                               relation=row[1]['relation'],
                                               predicate=row[1]['predicate'],
                                               object_id=row[1]['id'],
                                               edgeprops=edge_props,
                                               primary_knowledge_source=row[1]['provenance'],
                                               aggregator_knowledge_sources=[self.provenance_id])
                            self.final_edge_list.append(new_edge)
            else:
                self.logger.debug(f'node group mismatch. len: {len(rows)}, data: {rows}')


if __name__ == '__main__':
    # create a command line parser
    ap = argparse.ArgumentParser(description='Loads the PHAROS data from a MySQL DB and creates KGX import files.')

    # command line should be like: python loadPHAROS.py -p D:\Work\Robokop\Data_services\PHAROS_data -m json
    ap.add_argument('-s', '--data_dir', required=True, help='The location of the output directory')

    # parse the arguments
    args = vars(ap.parse_args())

    # get the params
    data_dir: str = args['data_dir']

    # get a reference to the processor
    pdb = PHAROSLoader()

    # load the data and create KGX output
    pdb.load(data_dir, data_dir)
