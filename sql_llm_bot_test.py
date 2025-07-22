import streamlit as st
import openai
import pandas as pd
import json

st.set_page_config(page_title="LLM-powered SQL Query Generator", layout="centered")

st.title("🤖 LLM-Powered SQL Query Generator")

st.markdown("""
Ask any question about the **i2b2 clinical database schema**, and I’ll generate:
- The **MySQL query**
- Example **input tables**
- Example **output table**
""")

# Use Streamlit secrets for OpenAI API key
openai.api_key = st.secrets["OPENAI_API_KEY"]

schema_description = """
- observation_fact: encounter_num, patient_num, concept_cd, start_date
- patient_dimension: patient_num, birth_date, death_date, sex_cd, race_cd, ethnicity_cd, language_cd, marital_status_cd, zip_cd
- concept_dimension: concept_cd, name_char
- visit_dimension: encounter_id, patient_num, start_date, end_date
"""

user_request = st.text_input("💬 What do you want to query?")

if user_request:
    with st.spinner("Generating SQL and examples…"):
        prompt = f"""
You are a MySQL expert and teacher. Given the i2b2 database schema, which contains tables like:

{schema_description}

And the user request: "{user_request}"

Generate a JSON with three fields:
- sql: the MySQL query
- input_tables: a dictionary where each key is a table name and value is a list of example rows (each row is a dictionary)
- output_table: a list of example rows (each row is a dictionary)

The JSON must be valid and parsable. Use realistic example values.

Return only the JSON.
"""

        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0
        )

        content = response.choices[0].message.content.strip()
        try:
            result = json.loads(content)

            st.subheader("✅ Generated SQL Query:")
            st.code(result["sql"], language="sql")

            if result.get("input_tables"):
                st.markdown("### 📥 Example Input Tables")
                for table_name, rows in result["input_tables"].items():
                    df = pd.DataFrame(rows)
                    st.markdown(f"**`{table_name}`**")
                    st.dataframe(df)

            if result.get("output_table"):
                st.markdown("### 📤 Example Output Table")
                df_out = pd.DataFrame(result["output_table"])
                st.dataframe(df_out)

        except Exception as e:
            st.error(f"Failed to parse response: {e}")
            st.text_area("Raw response:", content, height=300)
