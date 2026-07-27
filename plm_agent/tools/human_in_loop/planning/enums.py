tools = ["Catalyst-Event-Analysis", "Medical-Search", "Web-Search", "Finance-Search", "Patent-Search", "News-Search", "Drug-Manual-Search", "Clinical-Guideline-Search", "Clinical-Trial-Result-Analysis", "Drug-Analysis", "General-Inference", "Self-Reflection", "Generate-Summary", "Medical-Diagnosis", "Document-Read"]
# "Sandbox-Execution" removed from planning tools — sandbox works better as a tool within other HITL agents (finance, web, document-read)

phases = ["I", "II", "III", "IV", "Preclinical", "Others"]

phases_2 = ['Preclinical', 'IND', 'I', 'II', 'III', 'Suspended', 'BLA/NDA', 'Approved', 'IV', 'Withdrawn from Market', 'Investigator Initiated - phase unknown', 'Unknown', 'Others']

drug_features = ['Precision Medicine', 'Reformulation', 'Bacterial Product', '505b2', 'Immuno-Oncology', 'Biosimilar', 'Fixed-Dose Combination', 'Device', 'Non-NME', 'Specialty Drug', 'Viral', 'Biologic', 'New Molecular Entity (NME)']

drug_modality = ['Steroids', 'Vaccine', 'Antisense RNA', 'Antibody-Drug Conjugates, ADCs', 'Unknown', 'Protein Degrader', 'Monoclonal Antibodies', 'mRNA', 'Others', 'Cell-based Therapies', 'Imaging Agents', 'Gene Therapy', 'miRNA', 'Polypeptide', 'Recombinant Proteins', 'Small Molecule', 'siRNA/RNAi', 'Trispecific Antibodies', 'Polyclonal Antibodies', 'Bi-specific Antibodies', 'Glycoconjugates', 'Radiopharmaceutical']

route_of_administration = ['Inhaled', 'Intranasal', 'Transdermal', 'Intrathecal Injection', 'Intradermal Injection', 'Intraarticular Injection', 'Intraarterial Injection', 'Surgical Implantation', 'Subcutaneous Injection', 'Intraocular Injection', 'Intratumoral Injection', 'Intravenous (IV)', 'Intracavitary Injection', 'Oral (PO)', 'Intramuscular (IM) Injection', 'Percutaneous Catheter/Injection', 'Unknown', 'Intracerebral/cerebroventricular Injection', 'Others', 'Sublingual (SL)/Oral Transmucosal', 'Intravaginal', 'Rectal', 'Injectable (Others)', 'Intravesical Injection', 'Topical']

gender = ['Male', 'Female', 'Both']

current_status = ['Suspended', 'Initiated', 'Final Data', 'Completed', 'Announced', 'Enrolled', 'Interim Data Released']

catalyst_types = ['PDUFA Approval', 'Top-Line Results', 'Trial Data Update']

locations = ['China', 'United States', 'Japan', 'United Kingdom', 'France', 'Germany', 'Italy', 'Spain']

medical_common_field_list = [
    "indication_name", "company", "target", "phase",
    "drug_modality", "drug_feature", "route_of_administration"]

clinical_results_field_list = [
    "drug_name", "nctids", "locations"] + medical_common_field_list

drug_competition_landscape_field_list = [
    "drug_names", "location", "phase"] + medical_common_field_list

catalyst_search_field_list = [
    "phases", "indication_name", "company", "drug_name", "catalyst_type"
]

medical_common_field_list_not_apply = [
    "target", 
    "drug_modality", "drug_feature", "route_of_administration"]

clinical_results_field_list_not_apply = [
    "drug_name", "locations"] + medical_common_field_list_not_apply

drug_competition_landscape_field_list_not_apply = [
    "drug_names"] + medical_common_field_list_not_apply

catalyst_search_field_list_not_apply = [
    "drug_name"
]

