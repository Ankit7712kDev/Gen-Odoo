# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, _logger
import json
import re


def safe_json_parse(text):
    """
    Try to repair and safely parse JSON text from LLM output.
    Handles minor format errors from the model.
    """
    if not text:
        raise ValueError("Empty response from LLM.")

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON-like structure
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                fixed = match.group(0)
                # Remove trailing commas, newlines, etc.
                fixed = re.sub(r',\s*([\]}])', r'\1', fixed)
                fixed = re.sub(r'[\r\n]+', ' ', fixed)
                return json.loads(fixed)
            except json.JSONDecodeError as e2:
                raise ValueError(f"Invalid JSON format even after repair: {e2}\nRaw Output: {text}")
        else:
            raise ValueError(f"No JSON structure found in: {text}")




class NLPQueryController(http.Controller):

    @http.route('/nlp/query_page', type='http', auth='user', website=True)
    def nlp_query_page(self, **kwargs):
        """Renders the main NLP Query Assistant page."""
        return request.render('nlp_query_assistant.nlp_query_page', {})

    @http.route('/nlp/run_query', type='http', auth='user', methods=['POST'], csrf=False)
    def run_query(self, **kwargs):
        """
        Handle the POST request from frontend and call NLP service.
        Returns always valid JSON with HTML-ready result.
        """
        try:
            # Handle both raw fetch() JSON and form-encoded submissions
            data = request.httprequest.get_json(force=True, silent=True)
        except Exception:
            data = None

        query = (data or {}).get('query')
        if not query:
            return http.Response(
                json.dumps({'result': '⚠️ No query provided.'}),
                content_type='application/json'
            )

        try:
            result = request.env['nlp.query.service'].sudo().run_llm_query(query)

            # 🔧 Cleanup any unwanted log-style lines like "❌ Error: No JSON structure found"
            if isinstance(result, str):
                result = result.replace("❌ Error: No JSON structure found in:", "")
                # Remove blank lines or stray line breaks
                result = result.strip()

            return http.Response(
                json.dumps({'result': result or 'No data found.'}),
                content_type='application/json'
            )

        except Exception as e:
            _logger.exception("Error while processing NLP query")
            safe_error = str(e).split("\n")[0]
            return http.Response(
                json.dumps({'result': f"<div style='color:red;'>❌ Server Error: {safe_error}</div>"}),
                content_type='application/json'
            )

