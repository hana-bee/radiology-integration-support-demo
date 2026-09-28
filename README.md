**# Radiology Integration \& Technical Support System**



**## Project Overview**



**This project is an educational simulation of a healthcare**

**radiology integration environment.**



**It demonstrates the simplified workflow between:**



**HIS → HL7 → RIS → Modality → DICOM → PACS**



**The project also includes basic SQL database operations,**

**network diagnostics, system logging and technical support**

**troubleshooting scenarios.**



**---**



**## Project Objectives**



**The main objectives are:**



**1. Demonstrate understanding of healthcare IT systems.**

**2. Simulate HL7 order exchange between HIS and RIS.**

**3. Generate and read DICOM medical imaging metadata.**

**4. Demonstrate a simplified RIS Worklist.**

**5. Use SQL for storing and retrieving healthcare data.**

**6. Perform basic TCP/network diagnostics.**

**7. Simulate a DICOM/PACS communication failure.**

**8. Demonstrate a structured technical troubleshooting approach.**



**---**



**## Technologies Used**



**- Python**

**- Flask**

**- SQLite**

**- SQL**

**- pydicom**

**- HTML**

**- CSS**

**- TCP/IP socket testing**



**---**



**## Radiology Workflow**



**```text**

&#x20;                   **Hospital Environment**



&#x20;                        **HIS**

&#x20;                         **|**

&#x20;                        **HL7**

&#x20;                         **|**

&#x20;                         **v**

&#x20;                        **RIS**

&#x20;                         **|**

&#x20;                 **Modality Worklist**

&#x20;                         **|**

&#x20;                         **v**

&#x20;                     **CT Modality**

&#x20;                         **|**

&#x20;                      **DICOM**

&#x20;                         **|**

&#x20;                         **v**

&#x20;                       **PACS**

&#x20;                         **|**

&#x20;                         **v**

&#x20;                   **Radiologist**

