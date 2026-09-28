from flask import Flask, render_template, redirect, url_for
import sqlite3
from datetime import datetime
import os
import socket
import pydicom

from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import (
    CTImageStorage,
    ExplicitVRLittleEndian,
    generate_uid
)


app = Flask(__name__)

DATABASE = "radiology.db"
DICOM_FOLDER = "dicom"

# Simulated technical support failure state
dicom_failure = False


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db():

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# DATABASE INITIALIZATION
# =========================================================

def initialize_database():

    conn = get_db()
    cursor = conn.cursor()

    # Patients table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id TEXT PRIMARY KEY,
            patient_name TEXT NOT NULL,
            date_of_birth TEXT,
            gender TEXT
        )
    """)

    # Radiology Orders table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS orders (
            order_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            modality TEXT NOT NULL,
            study_description TEXT,
            status TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    # Radiology Studies table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS studies (
            study_id TEXT PRIMARY KEY,
            patient_id TEXT NOT NULL,
            modality TEXT,
            study_date TEXT,
            study_description TEXT,
            status TEXT,
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)

    # System Logs table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS system_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            system_name TEXT NOT NULL,
            event TEXT NOT NULL,
            status TEXT NOT NULL,
            message TEXT
        )
    """)

    # HL7 Messages table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS hl7_messages (
            message_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            message_type TEXT NOT NULL,
            raw_message TEXT NOT NULL,
            parsed_status TEXT NOT NULL
        )
    """)

    # Create demo data only when database is empty
    cursor.execute("SELECT COUNT(*) FROM patients")
    patient_count = cursor.fetchone()[0]

    if patient_count == 0:

        # Demo patient
        cursor.execute("""
            INSERT INTO patients
            (patient_id, patient_name, date_of_birth, gender)
            VALUES (?, ?, ?, ?)
        """, (
            "P001",
            "Ahmed Hassan",
            "1998-05-10",
            "Male"
        ))

        # Initial radiology order
        cursor.execute("""
            INSERT INTO orders
            (order_id, patient_id, modality,
             study_description, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            "O001",
            "P001",
            "CT",
            "Chest CT",
            "Scheduled"
        ))

        # Initial study
        cursor.execute("""
            INSERT INTO studies
            (study_id, patient_id, modality,
             study_date, study_description, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            "ST001",
            "P001",
            "CT",
            "2026-09-28",
            "Chest CT",
            "Stored in PACS"
        ))

        # Initial logs
        logs = [
            (
                "2026-09-28 10:01",
                "HIS",
                "Patient Registration",
                "SUCCESS",
                "Patient P001 registered successfully"
            ),
            (
                "2026-09-28 10:03",
                "HL7",
                "Order Received",
                "SUCCESS",
                "Radiology order O001 received"
            ),
            (
                "2026-09-28 10:05",
                "RIS",
                "Order Scheduled",
                "SUCCESS",
                "CT examination scheduled"
            ),
            (
                "2026-09-28 10:10",
                "DICOM",
                "Image Transfer",
                "SUCCESS",
                "DICOM study transferred to PACS"
            ),
            (
                "2026-09-28 10:11",
                "PACS",
                "Study Storage",
                "SUCCESS",
                "Study ST001 stored successfully"
            )
        ]

        cursor.executemany("""
            INSERT INTO system_logs
            (timestamp, system_name,
             event, status, message)
            VALUES (?, ?, ?, ?, ?)
        """, logs)

    conn.commit()
    conn.close()


# =========================================================
# HL7 MESSAGE GENERATOR
# =========================================================

def generate_hl7_order(
    patient_id,
    patient_name,
    order_id
):

    timestamp = datetime.now().strftime(
        "%Y%m%d%H%M%S"
    )

    name_parts = patient_name.split(" ", 1)

    given_name = name_parts[0]

    family_name = (
        name_parts[1]
        if len(name_parts) > 1
        else ""
    )

    hl7_message = (
        f"MSH|^~\\&|HIS|HOSPITAL|RIS|RADIOLOGY|"
        f"{timestamp}||ORM^O01|MSG{timestamp}|P|2.4\r"
        f"PID|1||{patient_id}||"
        f"{family_name}^{given_name}||"
        f"19980510|M\r"
        f"ORC|NW|{order_id}||||SC\r"
        f"OBR|1|{order_id}||CT^Chest CT"
    )

    return hl7_message


# =========================================================
# HL7 MESSAGE PARSER
# =========================================================

def parse_hl7_message(message):

    segments = message.split("\r")

    parsed_data = {
        "patient_id": "",
        "patient_name": "",
        "order_id": "",
        "modality": "",
        "study_description": ""
    }

    for segment in segments:

        fields = segment.split("|")

        if fields[0] == "PID":

            parsed_data["patient_id"] = fields[3]

            name = fields[5].split("^")

            if len(name) >= 2:

                parsed_data["patient_name"] = (
                    f"{name[1]} {name[0]}"
                )

            else:

                parsed_data["patient_name"] = name[0]

        elif fields[0] == "ORC":

            parsed_data["order_id"] = fields[2]

        elif fields[0] == "OBR":

            service = fields[4].split("^")

            if len(service) >= 2:

                parsed_data["modality"] = service[0]

                parsed_data["study_description"] = (
                    service[1]
                )

            else:

                parsed_data["modality"] = fields[4]

    return parsed_data


# =========================================================
# CREATE DICOM FILE
# =========================================================

def create_dicom_file(
    patient_id,
    patient_name,
    study_id
):

    os.makedirs(
        DICOM_FOLDER,
        exist_ok=True
    )

    study_uid = generate_uid()
    series_uid = generate_uid()
    sop_instance_uid = generate_uid()

    file_meta = FileMetaDataset()

    file_meta.MediaStorageSOPClassUID = (
        CTImageStorage
    )

    file_meta.MediaStorageSOPInstanceUID = (
        sop_instance_uid
    )

    file_meta.TransferSyntaxUID = (
        ExplicitVRLittleEndian
    )

    file_meta.ImplementationClassUID = (
        generate_uid()
    )

    file_name = os.path.join(
        DICOM_FOLDER,
        f"{study_id}.dcm"
    )

    ds = FileDataset(
        file_name,
        {},
        file_meta=file_meta,
        preamble=b"\0" * 128
    )

    ds.is_little_endian = True
    ds.is_implicit_VR = False

    # Patient information
    ds.PatientName = patient_name
    ds.PatientID = patient_id

    # Study information
    ds.Modality = "CT"
    ds.StudyDescription = "Chest CT"
    ds.BodyPartExamined = "CHEST"

    ds.StudyDate = datetime.now().strftime(
        "%Y%m%d"
    )

    ds.StudyTime = datetime.now().strftime(
        "%H%M%S"
    )

    ds.StudyInstanceUID = study_uid
    ds.SeriesInstanceUID = series_uid
    ds.SOPInstanceUID = sop_instance_uid
    ds.SOPClassUID = CTImageStorage

    ds.AccessionNumber = study_id

    ds.SeriesNumber = "1"
    ds.InstanceNumber = "1"

    # Image information
    ds.Rows = 128
    ds.Columns = 128

    ds.SamplesPerPixel = 1

    ds.PhotometricInterpretation = (
        "MONOCHROME2"
    )

    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0

    # Simple grayscale image
    pixel_data = bytes(
        [120] * (128 * 128)
    )

    ds.PixelData = pixel_data

    ds.save_as(
        file_name,
        write_like_original=False
    )

    return file_name


# =========================================================
# READ DICOM METADATA
# =========================================================

def read_dicom_metadata(file_name):

    ds = pydicom.dcmread(file_name)

    metadata = {

        "patient_name":
            str(ds.PatientName),

        "patient_id":
            str(ds.PatientID),

        "modality":
            str(ds.Modality),

        "study_description":
            str(ds.StudyDescription),

        "study_date":
            str(ds.StudyDate),

        "accession_number":
            str(ds.AccessionNumber),

        "study_uid":
            str(ds.StudyInstanceUID),

        "series_uid":
            str(ds.SeriesInstanceUID)

    }

    return metadata


# =========================================================
# TCP PORT CHECK
# =========================================================

def check_tcp_port(host, port):

    try:

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        sock.settimeout(2)

        result = sock.connect_ex(
            (host, port)
        )

        sock.close()

        return result == 0

    except Exception:

        return False


# =========================================================
# MAIN DASHBOARD
# =========================================================

@app.route("/")
def home():

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        LIMIT 1
    """).fetchone()

    order = conn.execute("""
        SELECT
            o.*,
            p.patient_name
        FROM orders o
        JOIN patients p
        ON o.patient_id = p.patient_id
        ORDER BY o.rowid DESC
        LIMIT 1
    """).fetchone()

    study = conn.execute("""
        SELECT
            s.*,
            p.patient_name
        FROM studies s
        JOIN patients p
        ON s.patient_id = p.patient_id
        ORDER BY s.rowid DESC
        LIMIT 1
    """).fetchone()

    logs = conn.execute("""
        SELECT *
        FROM system_logs
        ORDER BY log_id DESC
        LIMIT 8
    """).fetchall()

    latest_hl7 = conn.execute("""
        SELECT *
        FROM hl7_messages
        ORDER BY message_id DESC
        LIMIT 1
    """).fetchone()

    conn.close()

    if dicom_failure:

        support_status = "FAILURE"

        support_message = (
            "DICOM communication failure detected. "
            "Check network connectivity, PACS IP, "
            "DICOM port, AE Title, firewall and "
            "PACS service."
        )

    else:

        support_status = "NORMAL"

        support_message = (
            "All simulated radiology integration "
            "services are operating normally."
        )

    return render_template(
        "index.html",
        patient=patient,
        order=order,
        study=study,
        logs=logs,
        latest_hl7=latest_hl7,
        support_status=support_status,
        support_message=support_message
    )


# =========================================================
# SEND HL7 ORDER
# =========================================================

@app.route("/send-hl7")
def send_hl7():

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        LIMIT 1
    """).fetchone()

    count = conn.execute("""
        SELECT COUNT(*)
        FROM orders
    """).fetchone()[0]

    new_order_id = f"O{count + 1:03d}"

    hl7_message = generate_hl7_order(
        patient["patient_id"],
        patient["patient_name"],
        new_order_id
    )

    parsed = parse_hl7_message(
        hl7_message
    )

    conn.execute("""
        INSERT INTO orders
        (order_id, patient_id, modality,
         study_description, status)
        VALUES (?, ?, ?, ?, ?)
    """, (
        parsed["order_id"],
        parsed["patient_id"],
        parsed["modality"],
        parsed["study_description"],
        "Received via HL7"
    ))

    conn.execute("""
        INSERT INTO hl7_messages
        (timestamp, message_type,
         raw_message, parsed_status)
        VALUES (?, ?, ?, ?)
    """, (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "ORM^O01",
        hl7_message,
        "SUCCESS"
    ))

    conn.execute("""
        INSERT INTO system_logs
        (timestamp, system_name,
         event, status, message)
        VALUES (?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "HL7",
        "ORM Order Processing",
        "SUCCESS",
        f"Order {new_order_id} "
        f"parsed and stored in RIS"
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("home")
    )


# =========================================================
# GENERATE DICOM
# =========================================================

@app.route("/generate-dicom")
def generate_dicom():

    conn = get_db()

    patient = conn.execute("""
        SELECT *
        FROM patients
        LIMIT 1
    """).fetchone()

    study_count = conn.execute("""
        SELECT COUNT(*)
        FROM studies
    """).fetchone()[0]

    new_study_id = (
        f"ST{study_count + 1:03d}"
    )

    file_name = create_dicom_file(
        patient["patient_id"],
        patient["patient_name"],
        new_study_id
    )

    metadata = read_dicom_metadata(
        file_name
    )

    conn.execute("""
        INSERT INTO studies
        (study_id, patient_id, modality,
         study_date, study_description, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (
        new_study_id,
        metadata["patient_id"],
        metadata["modality"],
        metadata["study_date"],
        metadata["study_description"],
        "Stored in PACS"
    ))

    conn.execute("""
        INSERT INTO system_logs
        (timestamp, system_name,
         event, status, message)
        VALUES (?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "DICOM",
        "C-STORE Simulation",
        "SUCCESS",
        f"DICOM study {new_study_id} "
        f"generated and stored"
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("home")
    )


# =========================================================
# DICOM INFORMATION
# =========================================================

@app.route("/dicom-info")
def dicom_info():

    if not os.path.exists(DICOM_FOLDER):

        return "No DICOM folder found."

    dicom_files = [
        f
        for f in os.listdir(DICOM_FOLDER)
        if f.endswith(".dcm")
    ]

    if not dicom_files:

        return "No DICOM file found."

    latest_file = sorted(dicom_files)[-1]

    file_path = os.path.join(
        DICOM_FOLDER,
        latest_file
    )

    metadata = read_dicom_metadata(
        file_path
    )

    return render_template(
        "dicom.html",
        metadata=metadata,
        file_name=latest_file
    )


# =========================================================
# NETWORK DIAGNOSTICS
# =========================================================

@app.route("/network-test")
def network_test():

    host = "127.0.0.1"

    flask_port = 5000

    dicom_port = 11112

    try:

        resolved_ip = socket.gethostbyname(
            "localhost"
        )

        dns_status = True

    except socket.gaierror:

        resolved_ip = "Not resolved"

        dns_status = False

    application_status = check_tcp_port(
        host,
        flask_port
    )

    dicom_status = check_tcp_port(
        host,
        dicom_port
    )

    results = {

        "host":
            host,

        "resolved_ip":
            resolved_ip,

        "dns_status":
            dns_status,

        "application_port":
            flask_port,

        "application_status":
            application_status,

        "dicom_port":
            dicom_port,

        "dicom_status":
            dicom_status
    }

    return render_template(
        "network.html",
        results=results
    )


# =========================================================
# SIMULATE DICOM FAILURE
# =========================================================

@app.route("/simulate-failure")
def simulate_failure():

    global dicom_failure

    dicom_failure = True

    conn = get_db()

    conn.execute("""
        INSERT INTO system_logs
        (timestamp, system_name,
         event, status, message)
        VALUES (?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "DICOM",
        "Communication Failure",
        "ERROR",
        "DICOM association failed. "
        "PACS image transfer unavailable."
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("home")
    )


# =========================================================
# RESET SYSTEM
# =========================================================

@app.route("/reset-system")
def reset_system():

    global dicom_failure

    dicom_failure = False

    conn = get_db()

    conn.execute("""
        INSERT INTO system_logs
        (timestamp, system_name,
         event, status, message)
        VALUES (?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "SYSTEM",
        "System Reset",
        "SUCCESS",
        "Simulated DICOM/PACS failure cleared."
    ))

    conn.commit()
    conn.close()

    return redirect(
        url_for("home")
    )


# =========================================================
# RIS WORKLIST
# =========================================================

@app.route("/ris-worklist")
def ris_worklist():

    conn = get_db()

    orders = conn.execute("""
        SELECT
            o.order_id,
            o.patient_id,
            p.patient_name,
            o.modality,
            o.study_description,
            o.status
        FROM orders o
        JOIN patients p
        ON o.patient_id = p.patient_id
        ORDER BY o.rowid DESC
    """).fetchall()

    conn.close()

    return render_template(
        "worklist.html",
        orders=orders
    )


# =========================================================
# SQL DATABASE EXPLORER
# =========================================================

@app.route("/sql-explorer")
def sql_explorer():

    conn = get_db()

    # Count patients
    patient_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM patients
    """).fetchone()["count"]

    # Count orders
    order_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM orders
    """).fetchone()["count"]

    # Count studies
    study_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM studies
    """).fetchone()["count"]

    # Count HL7 messages
    hl7_count = conn.execute("""
        SELECT COUNT(*) AS count
        FROM hl7_messages
    """).fetchone()["count"]

    # SQL JOIN demonstration
    joined_data = conn.execute("""
        SELECT
            p.patient_id,
            p.patient_name,
            o.order_id,
            o.modality,
            o.study_description,
            o.status
        FROM patients p
        JOIN orders o
        ON p.patient_id = o.patient_id
        ORDER BY o.rowid DESC
    """).fetchall()

    # Studies
    studies = conn.execute("""
        SELECT
            study_id,
            patient_id,
            modality,
            study_date,
            study_description,
            status
        FROM studies
        ORDER BY rowid DESC
    """).fetchall()

    # Recent logs
    recent_logs = conn.execute("""
        SELECT
            timestamp,
            system_name,
            event,
            status
        FROM system_logs
        ORDER BY log_id DESC
        LIMIT 6
    """).fetchall()

    conn.close()

    return render_template(
        "sql.html",
        patient_count=patient_count,
        order_count=order_count,
        study_count=study_count,
        hl7_count=hl7_count,
        joined_data=joined_data,
        studies=studies,
        recent_logs=recent_logs
    )


# =========================================================
# RUN APPLICATION
# =========================================================

if __name__ == "__main__":

    initialize_database()

    app.run(
        debug=False,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000))
    )