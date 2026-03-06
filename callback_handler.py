"""
Simple callback handler for Upstox OAuth redirect.

Run this on port 8000 to receive the authorization code from Upstox.
Then manually paste the code into the Streamlit login page.

Usage:
    python callback_handler.py
"""

from flask import Flask, request
import sys

app = Flask(__name__)

@app.route('/callback')
def callback():
    code = request.args.get('code')
    state = request.args.get('state')
    
    if code:
        html = f"""
        <html>
        <head><title>Upstox Authorization</title></head>
        <body style="font-family: Arial; padding: 40px; background: #f5f5f5;">
            <div style="max-width: 600px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">
                <h1 style="color: #333;">✅ Authorization Successful</h1>
                <p style="font-size: 16px; color: #666;">
                    You have successfully authorized the Upstox API. 
                    Copy the code below and paste it into the Streamlit app, or the app may handle it automatically.
                </p>
                <div style="background: #f0f0f0; padding: 15px; border-radius: 4px; margin: 20px 0;">
                    <p style="margin: 0; color: #999; font-size: 12px;">Authorization Code:</p>
                    <p style="margin: 10px 0 0 0; font-size: 18px; font-weight: bold; color: #333; word-break: break-all;">
                        {code}
                    </p>
                </div>
                <p style="font-size: 14px; color: #999;">
                    You can now close this window and return to the Streamlit app.
                </p>
            </div>
        </body>
        </html>
        """
        return html
    else:
        return "Error: No authorization code received.", 400

if __name__ == '__main__':
    print("🚀 Callback handler listening on https://localhost:8000")
    print("Click the auth link in Streamlit, authorize, and you'll be redirected here.")
    print("The code will be displayed on this page.")
    app.run(ssl_context='adhoc', host='0.0.0.0', port=8000, debug=False)
