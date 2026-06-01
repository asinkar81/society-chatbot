"""
Initialize sample data for testing
"""
import sys
sys.path.insert(0, '/Users/ashutoshsinkar/society-chatbot')

from data_providers.local_excel_provider import LocalExcelDataProvider
import config

def create_sample_data():
    """Create sample members for testing"""
    
    # Initialize data provider
    provider = LocalExcelDataProvider(config.SOCIETY_DATA_FILE)
    
    # Sample members (Plot 1-41)
    sample_members = [
        {"Plot_No": "01", "Plot_Owner_Name": "Mrs. Asha Ganpat Dalvi", "Email": "", "Phone": "9423003232", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "02", "Plot_Owner_Name": "Mr. Chintamani Govind Raut", "Email": "", "Phone": "8007296753", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "03", "Plot_Owner_Name": "Mr. Nitin Ombale / Dhanahbri Bidkar", "Email": "", "Phone": "9822196328", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "04", "Plot_Owner_Name": "Mrs. Dhanashri Jagannath Bidkar", "Email": "", "Phone": "9822196328", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "05", "Plot_Owner_Name": "Mr. Chandrashekhar Anushil Rathod", "Email": "anshulrathod@gmail.com", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "06", "Plot_Owner_Name": "Mrs. Viral Vijay Nimbkar", "Email": "", "Phone": "7770069005", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "07", "Plot_Owner_Name": "Mr. Williams George Fernandes", "Email": "", "Phone": "8605165548", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "08", "Plot_Owner_Name": "Mr. Shantanu Kulkarni & Mrs. Yogita Kulkarni", "Email": "shantanusk@gmail.com", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "09", "Plot_Owner_Name": "Mr. Kunal Madhukar Chavan / Siddhant Madhukar Chavan", "Email": "", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "10", "Plot_Owner_Name": "Mrs. Shruti Avinash Bhagwat & Mr. Avinash Balakrishna Bhagwat", "Email": "", "Phone": "9146013244", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "11", "Plot_Owner_Name": "Mr. Ramdan Gangaram Salvi", "Email": "ramesalvi@gmail.com", "Phone": "9970943745", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "12", "Plot_Owner_Name": "Mr. Madikiar Madhukar & Savitri Maskikar", "Email": "", "Phone": "9422539862", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "13", "Plot_Owner_Name": "Mr. Rishikesh Arun Phuslane", "Email": "pikaantouris@gmail.com", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "14", "Plot_Owner_Name": "Mr. Ramdan Gangaram Salvi", "Email": "", "Phone": "9970943745", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "15", "Plot_Owner_Name": "Mr. Satyajit Shete", "Email": "", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "16", "Plot_Owner_Name": "Ms. Tejashree Shrikant Bhate", "Email": "", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "17", "Plot_Owner_Name": "Ms. Tejashree Shrikant Bhate", "Email": "", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "18", "Plot_Owner_Name": "Mrs. Manjiri Abhijit Gavande & M/s Manshi Industries", "Email": "", "Phone": "9960184874", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "19", "Plot_Owner_Name": "Mrs. Sheetal Atul Salunke & M/s Manshi Industries", "Email": "", "Phone": "8767669660", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "20", "Plot_Owner_Name": "Mr. Anshul Rathod & Sweety Anshul Rathod", "Email": "anshulrathod@gmail.com", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "21", "Plot_Owner_Name": "Mr. Nilesh Pawar", "Email": "", "Phone": "9890616163", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "22", "Plot_Owner_Name": "Mr. Kaushubh Narendra Joshi & Mrs. Anusha Kaushubh Joshi", "Email": "", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "23", "Plot_Owner_Name": "Mr. Parag Modak & Mrs. Tanuja Parag Modak", "Email": "prmodak@gmail.com", "Phone": "9881900324", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "24", "Plot_Owner_Name": "Mr. Amit Vijay Bhosale", "Email": "", "Phone": "9850300423", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "25", "Plot_Owner_Name": "Mr. Achyuta Rao", "Email": "archyu15@yahoo.co.in", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "26", "Plot_Owner_Name": "Mr. Ashutosh Sinkar & Mrs. Snehal Ashutosh Sinkar", "Email": "ashutosh.sinkar@gmail.com", "Phone": "9890862540", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "27", "Plot_Owner_Name": "Mr. Rahul Bichkar", "Email": "", "Phone": "9923286314", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "28", "Plot_Owner_Name": "Mr. Mahutosh Vasant Pujari", "Email": "", "Phone": "9960184874", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "29", "Plot_Owner_Name": "Mr. Ashutosh Vasant Pujari", "Email": "", "Phone": "8767669660", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "30", "Plot_Owner_Name": "Mr. Kishore Haridas", "Email": "kishore.varier@gmail.com", "Phone": "8407927799", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "31", "Plot_Owner_Name": "Mrs. Suvarna Rahul Joshi", "Email": "", "Phone": "9890233305", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "33", "Plot_Owner_Name": "Mrs. Sangita Sunil Varpe", "Email": "", "Phone": "9422530521", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "34", "Plot_Owner_Name": "Mrs. Dhanashri Jagannath Bidkar", "Email": "", "Phone": "9822196328", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "35", "Plot_Owner_Name": "Mrs. Dhanashri Jagannath Bidkar", "Email": "", "Phone": "9822196328", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "36", "Plot_Owner_Name": "Mr. Rahul Palnitkar", "Email": "rahul.gtalk@gmail.com", "Phone": "9165416245", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "37", "Plot_Owner_Name": "Mr. Ajaykumar Radhakrishnan & Mrs. Saumya Ajaykumar", "Email": "", "Phone": "9423202483", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "38", "Plot_Owner_Name": "Mrs. Dhanashree Kuldeep Desipande", "Email": "", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "39", "Plot_Owner_Name": "Mrs. Dhanashree Kuldeep Desipande", "Email": "", "Phone": "", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "40", "Plot_Owner_Name": "Mrs. Rama Ramdas Salvi", "Email": "rama.salvi@gmail.com", "Phone": "9860582702", "Current_Outstanding": 0, "Pending_Interest": 0},
        {"Plot_No": "41", "Plot_Owner_Name": "Mr. Ramesh Dhebe", "Email": "", "Phone": "9373973989", "Current_Outstanding": 0, "Pending_Interest": 0},
    ]
    
    # Add remaining sample members if needed (for gaps in plot numbers)
    # Currently we have plots 1-41 (excluding 32) as per provided data
    
    # Add members to database
    added_count = 0
    for member in sample_members:
        try:
            member_id = provider.add_member(member)
            added_count += 1
            print(f"✓ Added: {member['Plot_Owner_Name']} (Plot {member['Plot_No']})")
        except Exception as e:
            print(f"✗ Failed to add {member['Plot_Owner_Name']}: {str(e)}")
    
    print(f"\nSample data created: {added_count}/{len(sample_members)} members added")
    
    # Verify
    all_members = provider.get_all_members()
    print(f"Total members in database: {len(all_members)}")


if __name__ == "__main__":
    print("Initializing sample data...")
    create_sample_data()
    print("Done!")
