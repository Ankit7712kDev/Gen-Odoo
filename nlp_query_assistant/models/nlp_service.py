from odoo import models, api
import requests
import json
import re
import logging

_logger = logging.getLogger(__name__)


class NLPService(models.AbstractModel):
    _name = 'nlp.query.service'
    _description = 'NLP Query Service using Local LLM (Ollama Llama3)'

    # ======================================================================
    # MAIN METHOD: Run Query and Return HTML
    # ======================================================================
    @api.model
    def run_llm_query(self, query):
        _logger.info(f"🔍 Received NLP query: {query}")

        # Detect 'top N' / 'first N'
        limit = None
        match = re.search(r'(?:top|first)\s+(\d+)', query, re.IGNORECASE)
        if match:
            limit = int(match.group(1))

        # Run query
        result = self.process_natural_query(query)
        if not result.get("success"):
            clean_error = re.sub(r'Raw Output:.*', '', result.get('error', ''), flags=re.DOTALL)
            return f"<div style='color:red;'>❌ Error: {clean_error.strip()}</div>"

        records = result.get("records", [])
        if not records:
            return "<div style='color:gray;'>ℹ️ No matching records found.</div>"

        # Apply limit
        if limit:
            records = records[:limit]

        # Determine columns
        all_keys = list(records[0].keys())
        all_keys = [k for k in all_keys if k not in ('__last_update', 'display_name')]

        total_records = len(records)
        truncated = False
        if total_records > 500:
            records = records[:500]
            truncated = True

        # ✅ Build HTML with custom icon
        html = f"""
        <div style="font-family: Inter, Arial, sans-serif; padding: 16px; background-color: #F9FAFB;">
            <h3 style="color:#1E3A8A; margin-bottom:10px; display:flex; align-items:center; gap:8px;">
                <img src="/nlp_query_assistant/static/description/icon.png"
                     alt="icon" width="35" height="35" style="vertical-align:middle;">
                Query Results
                <span style="font-size:13px; color:#6B7280;">
                    ({len(records)} shown{' of ' + str(total_records) if truncated else ''})
                </span>
            </h3>
            <div style="overflow-x:auto; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">
                <table style="border-collapse: collapse; width:100%; min-width:600px; font-size:14px;">
                    <thead style="background-color:#2563EB; color:white;">
                        <tr>
                            {''.join(f"<th style='text-align:left; padding:10px; border-right:1px solid #1D4ED8;'>{k.title()}</th>" for k in all_keys)}
                        </tr>
                    </thead>
                    <tbody style="background:white;">
                        {''.join(
            "<tr style='border-bottom:1px solid #E5E7EB;'>"
            + "".join(f"<td style='padding:8px; color:#374151;'>{rec.get(k, '') or '—'}</td>" for k in all_keys)
            + "</tr>"
            for rec in records
        )}
                    </tbody>
                </table>
            </div>
        </div>
        """

        if truncated:
            html += f"<p style='color:orange; margin-top:8px;'>⚠️ Showing only first 500 of {total_records} records for safety.</p>"

        return html

    # ======================================================================
    # CORE NLP → ORM LOGIC (with full JSON validation & repair)
    # ======================================================================
    @api.model
    def process_natural_query(self, query):
        prompt = f"""
        You are an Odoo database assistant. Convert the user query into a JSON block ONLY.
        No explanations, no markdown, no extra text — just valid JSON.

        Available models and fields:
        - res.partner (name, email, phone, city)
        - sale.order (name, partner_id, amount_total, date_order, state)
        - purchase.order (name, partner_id, amount_total, date_order, state)
        - account.move (name, partner_id, amount_total, invoice_date, move_type)

        Example:
        {{
            "model": "sale.order",
            "domain": [["partner_id.name", "ilike", "John"], ["state", "=", "draft"]],
            "fields": ["name", "amount_total", "date_order"]
        }}

        Now generate only the JSON for this query:
        "{query}"
        """

        try:
            # --- Step 1: Call Llama locally
            response = requests.post(
                "http://localhost:11434/api/generate",
                json={"model": "llama3", "prompt": prompt,"options": {"temperature": 0, "top_p": 1, "num_predict": 300},},
                stream=True,
                timeout=120,
            )
            if response.status_code != 200:
                return {"success": False, "error": f"LLM API error {response.status_code}"}

            # --- Step 2: Collect streamed response
            llm_output = ""
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "response" in data:
                        llm_output += data["response"]
                    if data.get("done"):
                        break
                except Exception:
                    continue

            llm_output = llm_output.strip()
            _logger.info(f"🤖 Raw LLM Output: {llm_output}")

            # --- Step 3: Extract JSON block
            match = re.search(r'\{[\s\S]*\}', llm_output)
            if match:
                json_text = match.group(0).strip()
            else:
                match = re.search(r'\[[\s\S]*\]', llm_output)
                json_text = match.group(0).strip() if match else None

            # --- Step 4: Repair unclosed or truncated JSON
            if json_text and not json_text.endswith('}'):
                if '"fields"' in json_text and not json_text.endswith('}]'):
                    json_text += ']}'
                elif not json_text.endswith('}'):
                    json_text += '}'

            if not json_text or not json_text.startswith('{'):
                _logger.warning("⚠️ No valid JSON object found, using fallback template.")
                json_text = '{"model": "res.partner", "domain": [], "fields": ["name"]}'

            # --- Step 5: Normalize JSON
            json_text = re.sub(r'\bFalse\b', 'false', json_text)
            json_text = re.sub(r'\bTrue\b', 'true', json_text)
            json_text = re.sub(r'\bNone\b', 'null', json_text)
            json_text = re.sub(r',\s*([\]}])', r'\1', json_text)
            json_text = re.sub(r'\s+', ' ', json_text).strip()

            _logger.info(f"🧩 Cleaned JSON text (final): {json_text}")

            # --- Step 6: Parse JSON safely
            try:
                parsed = json.loads(json_text)
            except Exception as e:
                _logger.warning(f"⚠️ JSON parsing failed ({e}), using fallback structure.")
                parsed = {"model": "res.partner", "domain": [], "fields": ["name"]}

            # --- Step 7: Ensure structure is dict
            if not isinstance(parsed, dict):
                _logger.warning("⚠️ Parsed JSON was not a dict, using fallback.")
                parsed = {"model": "res.partner", "domain": [], "fields": ["name"]}

            model = parsed.get("model", "res.partner")
            domain = parsed.get("domain", [])
            fields = parsed.get("fields", ["name"])

            if not model or model not in self.env:
                return {"success": False, "error": f"Model '{model}' not found in Odoo."}

            # --- Step 8: Auto-repair malformed domain
            fixed_domain = []
            for cond in domain:
                if not isinstance(cond, (list, tuple)):
                    continue
                if len(cond) == 1:
                    fixed_domain.append([cond[0], "!=", False])
                elif len(cond) == 2:
                    fixed_domain.append([cond[0], cond[1], False])
                else:
                    fixed_domain.append(cond)
            domain = fixed_domain
            _logger.info(f"🛠 Final repaired domain: {domain}")

            # --- Step 9: ORM search
            clean_fields = []
            for f in fields:
                base_field = f.split('.')[0]
                if base_field not in clean_fields:
                    clean_fields.append(base_field)

            records = self.env[model].sudo().search_read(domain, clean_fields)

            # --- Step 10: Expand relational fields
            for rec in records:
                for f in fields:
                    if '.' in f:
                        base, rel_field = f.split('.', 1)
                        val = rec.get(base)

                        if isinstance(val, (list, tuple)):
                            rec[f] = val[1] if len(val) > 1 else '—'
                        elif isinstance(val, dict):
                            rec[f] = val.get(rel_field, '—')
                        elif isinstance(val, str):
                            rec[f] = val
                        else:
                            rec[f] = '—'

            return {"success": True, "records": records}

        except Exception as e:
            _logger.exception("Error in NLP query processing")
            return {"success": False, "error": str(e)}
