import os
import argparse
from ViralProteome.src.loadVP import VPLoader
from ViralProteome.src.loadUniRef import UniRefSimLoader
from IntAct.src.loadIA import IALoader
from GOA.src.loadGOA import GOALoader
from UberGraph.src.loadUG import UGLoader
from FooDB.src.loadFDB import FDBLoader
from GTEx.src.loadGTEx import GTExLoader
from PHAROS.src.loadPHAROS import PHAROSLoader
from Common.utils import LoggingUtil
from pathlib import Path

# create a logger
logger = LoggingUtil.init_logging("Data_services.load_all", line_format='medium', log_file_path=os.path.join(Path(__file__).parents[0], 'logs'))


if __name__ == '__main__':
    """
    Parses both the UniProtKB viral proteome and UniRef data and creates KGX import files for each. 

    Example command lines:    
    python load_all.py -p D:/Work/Robokop/Data_services/UniProtKB_data -m tsv
    python load_all.py -r E:/Data_services/UniRef_data -f uniref100,uniref90,uniref50 -m tsv
    python load_all.py -i D:/Work/Robokop/Data_services/IntAct_data -m tsv
    python load_all.py -p D:/Work/Robokop/Data_services/UniProtKB_data -g goa_human.gaf.gz -m tsv
    python load_all.py -u D:/Work/Robokop/Data_services/UberGraph -s properties-nonredundant.ttl,properties-redundant.ttl -m tsv
    python load_all.py -o D:/Work/Robokop/Data_services/FooDB_data -m tsv
    python load_all.py -x D:/Work/Robokop/Data_services/GTEx_data -m tsv
    python load_all.py -a D:/Work/Robokop/Data_services/PHAROS_data -m tsv

    The full set of command line switches
        -p
        D:/Work/Robokop/Data_services/UniProtKB_data
        -r
        E:/Data_services/UniRef_data
        -f
        uniref100,uniref90,uniref50
        -i
        D:/Work/Robokop/Data_services/IntAct_data
        -g
        goa_human.gaf.gz
        -u
        D:/Work/Robokop/Data_services/Ubergraph_data
        -s
        properties-nonredundant.ttl
        -o
        D:/Work/Robokop/Data_services/FooDB_data
        -x
        D:/Work/Robokop/Data_services/GTEx_data
        -a
        D:/Work/Robokop/Data_services/PHAROS_data
        -m
        json
    """
    # create a command line parser
    ap = argparse.ArgumentParser(description='Load UniProtKB viral proteome, UniRef, Human GOA, UberGraph and IntAct data files and create KGX import files.')

    # declare command line arguments
    ap.add_argument('-p', '--uniprot_dir', required=False, help='The data directory for the UniProtKB GOA and KGX files (VP or Human).')
    ap.add_argument('-r', '--uniref_dir', required=False, help='The data directory for the 3 UniRef files and the KGX files.')
    ap.add_argument('-f', '--uniref_files', required=False, help='Comma separated UniRef data file(s) to parse.')
    ap.add_argument('-i', '--intact_dir', required=False, help='The data directory for the IntAct data and KGX files.')
    ap.add_argument('-g', '--goa_data_file', required=False, help='The name of the target GOA data file.')
    ap.add_argument('-u', '--ug_data_dir', required=False, help='The UberGraph data file directory.')
    ap.add_argument('-s', '--ug_data_files', required=False, help='Comma separated UberGraph data file(s) to parse.')
    ap.add_argument('-o', '--foodb_dir', required=False, help='The data directory for FooDB')
    ap.add_argument('-x', '--gtex_dir', required=False, help='The data directory for GTEx')
    ap.add_argument('-a', '--pharos_dir', required=False, help='The data directory for PHAROS')
    ap.add_argument('-m', '--out_mode', required=True, help='The output file mode (tsv or json)')

    # parse the arguments
    args = vars(ap.parse_args())

    # get the output mode
    out_mode = args['out_mode']

    # assign the uniprot dir
    UniProtKB_data_dir = args['uniprot_dir']

    if UniProtKB_data_dir is not None:
        # get a reference to the processor
        vp = VPLoader()

        # load the data files and create KGX output
        vp.load(UniProtKB_data_dir, 'Viral_proteome_GOA', out_mode)

    # assign the uniref directory and target files
    UniRef_data_dir = args['uniref_dir']
    UniRef_files = args['uniref_files']

    if UniRef_data_dir is not None and UniRef_files is not None:
        # get a reference to the processor
        uni = UniRefSimLoader()

        # load the data files and create KGX output
        uni.load(UniRef_data_dir, UniRef_files.split(','), 'taxon_file_indexes.txt', out_mode)

    # assign the intact directory
    IntAct_data_dir = args['intact_dir']

    if IntAct_data_dir is not None:
        # get a reference to the processor
        ia = IALoader()

        # load the data files and create KGX output files
        ia.load(IntAct_data_dir, 'intact', out_mode)

    # assign the target GOA data file
    GOA_data_file = args['goa_data_file']

    if UniProtKB_data_dir is not None:
        # get a reference to the processor
        goa = GOALoader()

        # load the data files and create KGX output files
        goa.load(UniProtKB_data_dir, GOA_data_file, 'Human_GOA', out_mode)

    # assign the ubergraph directory and target files
    UG_data_dir = args['ug_data_dir']
    UG_data_file = args['ug_data_files']

    if UG_data_dir is not None:
        # get a reference to the processor
        ug = UGLoader()

        # load the data files and create KGX output files
        ug.load(UG_data_dir, UG_data_file, out_mode, file_size=200000)

    # assign the foodb directory
    FDB_data_dir = args['foodb_dir']

    if FDB_data_dir is not None:
        # get a reference to the processor
        fdb = FDBLoader()

        # load the data files and create KGX output files
        fdb.load(FDB_data_dir, 'FooDB', out_mode)

    # assign the GTEx directory
    GTEx_data_dir = args['gtex_dir']

    if GTEx_data_dir is not None:
        # get a reference to the processor
        gtl = GTExLoader(test_data=True, use_cache=False)

        gtl.load(GTEx_data_dir, 'gtex_kgx')

    # assign the PHAROS directory
    PHAROS_data_dir = args['pharos_dir']

    if PHAROS_data_dir is not None:
        # get a reference to the processor
        pdb = PHAROSLoader()

        pdb.load(PHAROS_data_dir, 'pharos_kgx')
