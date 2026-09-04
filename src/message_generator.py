"""Message Generator — creates personalized recovery messages in English/Hinglish.

Generates empathetic, culturally appropriate payment recovery messages.
This is a KEY DIFFERENTIATOR for the buildathon — most submissions won't
support Hinglish.
"""

import json
from typing import Dict, Any, Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config import settings


# Message templates as fallback when LLM is unavailable
MESSAGE_TEMPLATES = {
    "english": {
        "empathetic": {
            "retry_payment": "Hi {name}! Your payment of ₹{amount} couldn't go through due to a temporary issue. Don't worry — we're retrying it for you automatically.",
            "send_payment_link": "Hi {name}! Your payment of ₹{amount} couldn't be processed ({reason}). No worries — here's a new payment link to complete your purchase: {link}",
            "offer_razorpay_paylater": "Hi {name}! Your payment of ₹{amount} failed due to low balance. Since you're a loyal customer, use Razorpay PayLater to clear it now and pay next month: {link}",
            "negotiate_retention": "Hi {name}. We noticed your payment of ₹{amount} failed. If you update your payment method today, we'll apply a 15% discount for the next 3 months: {link}",
            "escalate_to_human": "Hi {name}, we noticed your payment of ₹{amount} needs attention. Our support team will reach out to you shortly to help resolve this.",
        },
        "reminder": {
            "retry_payment": "Reminder: Your ₹{amount} payment is being retried. You'll receive a confirmation shortly.",
            "send_payment_link": "Reminder: Your ₹{amount} payment is still pending. Complete it here: {link}",
            "offer_razorpay_paylater": "Reminder: Complete your ₹{amount} payment instantly using Razorpay PayLater: {link}",
            "negotiate_retention": "Reminder: Update your payment today for a 15% discount: {link}",
            "escalate_to_human": "Your ₹{amount} payment requires assistance. A team member will contact you soon.",
        },
        "urgent": {
            "retry_payment": "{name}, your ₹{amount} payment failed. We're making a final retry attempt now.",
            "send_payment_link": "{name}, your ₹{amount} payment needs immediate attention. Please complete payment here: {link}",
            "offer_razorpay_paylater": "{name}, last chance to clear your ₹{amount} payment using Razorpay PayLater: {link}",
            "negotiate_retention": "{name}, your 15% discount offer expires soon. Update payment here: {link}",
            "escalate_to_human": "{name}, your ₹{amount} payment could not be processed. Our team is prioritizing your case.",
        },
    },
    "hinglish": {
        "empathetic": {
            "retry_payment": "Hi {name}! Aapka ₹{amount} ka payment temporary issue ki wajah se process nahi ho paya. Tension mat lijiye — hum automatically retry kar rahe hain.",
            "send_payment_link": "Hi {name}! Aapka ₹{amount} ka payment process nahi ho paya ({reason}). Koi baat nahi — is link se payment complete karein: {link}",
            "offer_razorpay_paylater": "Hi {name}! Aapka ₹{amount} payment low balance ki wajah se fail hua. Razorpay PayLater use karke abhi clear karein aur next month pay karein: {link}",
            "negotiate_retention": "Hi {name}. Aapka ₹{amount} ka payment fail ho gaya. Agar aaj payment method update karte hain, toh hum next 3 months ke liye 15% discount denge: {link}",
            "escalate_to_human": "Hi {name}, aapke ₹{amount} ke payment mein ek issue aaya hai. Humari team jaldi aapse contact karegi.",
        },
        "reminder": {
            "retry_payment": "Reminder: Aapka ₹{amount} payment retry ho raha hai. Confirmation jaldi milega.",
            "send_payment_link": "Reminder: Aapka ₹{amount} payment pending hai. Yahan se complete karein: {link}",
            "offer_razorpay_paylater": "Reminder: Apne ₹{amount} payment ko Razorpay PayLater se abhi clear karein: {link}",
            "negotiate_retention": "Reminder: 15% discount ke liye aaj hi payment method update karein: {link}",
            "escalate_to_human": "Aapke ₹{amount} payment mein humari help chahiye. Team jaldi contact karegi.",
        },
        "urgent": {
            "retry_payment": "{name}, aapka ₹{amount} ka payment fail ho gaya. Hum last retry kar rahe hain abhi.",
            "send_payment_link": "{name}, aapka ₹{amount} ka payment urgent hai! Abhi yahan se pay karein: {link}",
            "offer_razorpay_paylater": "{name}, Razorpay PayLater se payment clear karne ka last chance: {link}",
            "negotiate_retention": "{name}, aapka 15% discount offer jaldi expire hone wala hai: {link}",
            "escalate_to_human": "{name}, aapka ₹{amount} ka payment process nahi ho paya. Humari team priority pe aapka case dekh rahi hai.",
        },
    },
    "hindi": {
        "empathetic": {
            "retry_payment": "नमस्ते {name}! आपका ₹{amount} का भुगतान अस्थायी समस्या के कारण नहीं हो पाया। चिंता न करें — हम स्वचालित रूप से पुनः प्रयास कर रहे हैं।",
            "send_payment_link": "नमस्ते {name}! आपका ₹{amount} का भुगतान ({reason}) के कारण नहीं हो पाया। इस लिंक से भुगतान पूरा करें: {link}",
            "offer_razorpay_paylater": "नमस्ते {name}! कम बैलेंस के कारण आपका ₹{amount} का भुगतान विफल रहा। Razorpay PayLater का उपयोग करके अभी भुगतान करें और अगले महीने पैसे दें: {link}",
            "negotiate_retention": "नमस्ते {name}। आपका ₹{amount} का भुगतान विफल हो गया है। यदि आप आज भुगतान विधि अपडेट करते हैं, तो हम 15% छूट देंगे: {link}",
            "escalate_to_human": "नमस्ते {name}, आपके ₹{amount} के भुगतान में एक समस्या है। हमारी टीम जल्द ही संपर्क करेगी।",
        },
        "reminder": {
            "retry_payment": "अनुस्मारक: आपका ₹{amount} का भुगतान पुनः प्रयास हो रहा है।",
            "send_payment_link": "अनुस्मारक: आपका ₹{amount} का भुगतान लंबित है। यहाँ से पूरा करें: {link}",
            "offer_razorpay_paylater": "अनुस्मारक: Razorpay PayLater से अपना ₹{amount} भुगतान तुरंत पूरा करें: {link}",
            "negotiate_retention": "अनुस्मारक: 15% छूट के लिए आज ही भुगतान विधि अपडेट करें: {link}",
            "escalate_to_human": "आपके ₹{amount} के भुगतान में सहायता चाहिए। टीम जल्द संपर्क करेगी।",
        },
        "urgent": {
            "retry_payment": "{name}, आपका ₹{amount} का भुगतान विफल हो गया। अंतिम प्रयास किया जा रहा है।",
            "send_payment_link": "{name}, आपका ₹{amount} का भुगतान तुरंत आवश्यक है! यहाँ से भुगतान करें: {link}",
            "offer_razorpay_paylater": "{name}, Razorpay PayLater से भुगतान पूरा करने का अंतिम अवसर: {link}",
            "negotiate_retention": "{name}, आपकी 15% छूट जल्द समाप्त हो रही है: {link}",
            "escalate_to_human": "{name}, आपके ₹{amount} का भुगतान नहीं हो पाया। हमारी टीम प्राथमिकता पर है।",
        },
    },
}

# LLM prompt for generating custom messages
MESSAGE_GEN_PROMPT = """Generate a payment recovery message for an Indian customer.

Context:
- Customer Name: {name}
- Amount: ₹{amount}
- Failure Reason: {reason}
- Language: {language} (use natural, conversational {language})
- Tone: {tone}
- Action Being Taken: {action}
- Payment Link (if applicable): {link}

Rules:
1. Be empathetic and respectful
2. For Hinglish: mix Hindi and English naturally (like how urban Indians text)
3. Keep it under 160 characters for SMS compatibility when possible
4. Include the payment link if action is send_payment_link
5. Never be threatening or aggressive — Indian fintech compliance
6. Use ₹ symbol for amounts

Generate ONLY the message text, nothing else."""


class MessageGenerator:
    """Generates personalized recovery messages in multiple Indian languages."""
    
    def __init__(self):
        self.llm = self._init_llm()
    
    def _init_llm(self):
        """Initialize LLM for custom message generation."""
        if not settings.use_llm_in_hot_path:
            return None  # Force instant template resolution
            
        provider = settings.llm_provider.lower()
        try:
            if provider == "openai":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(model="gpt-4o-mini", temperature=0.7, api_key=settings.openai_api_key)
            elif provider == "anthropic":
                from langchain_anthropic import ChatAnthropic
                return ChatAnthropic(model="claude-3-haiku-20240307", temperature=0.7, api_key=settings.anthropic_api_key)
            elif provider == "google":
                from langchain_google_genai import ChatGoogleGenerativeAI
                return ChatGoogleGenerativeAI(model="gemini-1.5-flash", temperature=0.7, google_api_key=settings.google_api_key)
            return None
        except Exception:
            return None
    
    def generate_message(self, payment: Dict[str, Any], strategy: Dict[str, Any],
                         payment_link_url: str = None) -> Dict[str, str]:
        """Generate a personalized recovery message.
        
        Returns:
            Dict with 'message' and 'language' keys
        """
        customer = payment.get("customer", {})
        name = customer.get("name", "Customer").split()[0]  # First name only
        amount = payment.get("amount", 0)
        language = customer.get("language_pref", "english")
        action = strategy.get("action", "escalate_to_human")
        tone = strategy.get("message_tone", "empathetic")
        reason = payment.get("error_description", "a payment issue")
        link = payment_link_url or "[payment_link]"
        
        # Map language preference
        if language in ["hindi", "hinglish"]:
            lang_key = language
        else:
            lang_key = "english"
        
        # Try LLM first for more natural messages
        if self.llm is not None:
            try:
                llm_message = self._llm_generate(
                    name=name, amount=amount, reason=reason,
                    language=lang_key, tone=tone, action=action, link=link
                )
                if llm_message:
                    return {"message": llm_message, "language": lang_key}
            except Exception:
                pass  # Fall through to templates
        
        # Fallback to templates
        template = MESSAGE_TEMPLATES.get(lang_key, MESSAGE_TEMPLATES["english"])
        tone_templates = template.get(tone, template["empathetic"])
        message_template = tone_templates.get(action, tone_templates.get("escalate_to_human", ""))
        
        message = message_template.format(
            name=name, amount=f"{amount:,.0f}",
            reason=reason, link=link
        )
        
        return {"message": message, "language": lang_key}
    
    def _llm_generate(self, name: str, amount: float, reason: str,
                      language: str, tone: str, action: str, link: str) -> Optional[str]:
        """Generate a message using the LLM."""
        prompt = MESSAGE_GEN_PROMPT.format(
            name=name, amount=f"{amount:,.0f}", reason=reason,
            language=language, tone=tone, action=action, link=link
        )
        response = self.llm.invoke(prompt)
        return response.content.strip().strip('"').strip("'")
