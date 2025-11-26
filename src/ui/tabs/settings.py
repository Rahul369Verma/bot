import streamlit as st
import time

def render_settings_tab(fyers_manager):
    """Renders the Settings tab."""
    st.subheader("🔑 Fyers API Settings")
    if not fyers_manager:
        st.error("Fyers Manager failed to initialize. Check your .env file.")
        st.code("Create a .env file in the root directory with:\n\nFYERS_APP_ID=YOUR_APP_ID\nFYERS_SECRET_KEY=YOUR_SECRET_KEY\nFYERS_REDIRECT_URL=YOUR_NGROK_URL")
    else:
        st.info(f"**App ID:** `{fyers_manager.app_id[:4]}...{fyers_manager.app_id[-4:]}`")
        st.info(f"**Redirect URL:** `{fyers_manager.redirect_url}`")
        st.warning("Ensure your Redirect URL in the Fyers App Dashboard matches *exactly*.")
    
        if fyers_manager.is_authenticated():
            st.success("✅ Fyers API is authenticated and ready.")
            st.write(f"Your Access Token is saved in `fyers_token.json`")
            
            # --- NEW: Refresh Token Button ---
            st.divider()
            st.subheader("🔄 Refresh Token")
            st.info("If you've updated the token file manually or generated a new token, click below to reload it without restarting the app.")
            
            if st.button("🔄 Refresh Token from File", type="secondary", width='stretch'):
                with st.spinner("Reloading token..."):
                    if fyers_manager.reload_token():
                        # Signal bot to stop
                        if 'bot_stop_event' in st.session_state:
                            print("🛑 Signaling bot thread to stop...")
                            st.session_state.bot_stop_event.set()
                            # Optional: Wait a bit for it to stop, but don't block too long
                            time.sleep(1)
                        
                        # Clear session state related to bot
                        if 'bot_thread' in st.session_state:
                            del st.session_state.bot_thread
                        if 'bot_stop_event' in st.session_state:
                            del st.session_state.bot_stop_event
                            
                        # Clear the cached resource to force reinitialization
                        st.cache_resource.clear()
                        st.success("✅ Token reloaded successfully! The application will refresh now.")
                        st.rerun()
                    else:
                        st.error("❌ Failed to reload token. The token file may be missing or invalid.")
        else:
            st.error("Fyers API is not authenticated.")
            try:
                login_url = fyers_manager.get_login_url()
                st.link_button("1. Click here to log in to Fyers", login_url, type="primary")
                st.write("2. After logging in, you will be redirected back here. The app will automatically generate and save your token.")
            except Exception as e:
                st.error(f"Could not generate login URL: {e}")
