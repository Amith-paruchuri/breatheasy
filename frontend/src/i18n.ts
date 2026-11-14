/**
 * English / Hindi. Strings are written in English in the code and looked up here;
 * anything without a Hindi entry falls back to English. `{name}` placeholders are
 * filled from the vars argument. The choice is kept per device (localStorage) and can
 * be forced with ?lang=hi or ?lang=en in the URL.
 */
import { useSyncExternalStore } from "react";

export type Lang = "en" | "hi";

function initial(): Lang {
  try {
    const q = new URLSearchParams(window.location.search).get("lang");
    if (q === "hi" || q === "en") return q;
    const s = localStorage.getItem("br.lang");
    if (s === "hi" || s === "en") return s;
  } catch {
    /* storage blocked */
  }
  return typeof navigator !== "undefined" && /^hi\b/i.test(navigator.language) ? "hi" : "en";
}

let lang: Lang = typeof window === "undefined" ? "en" : initial();
const subs = new Set<() => void>();
if (typeof document !== "undefined") document.documentElement.lang = lang;

export const getLang = () => lang;
export function setLang(l: Lang) {
  lang = l;
  try {
    localStorage.setItem("br.lang", l);
  } catch {
    /* storage blocked */
  }
  document.documentElement.lang = l;
  subs.forEach((f) => f());
}
export function useLang(): Lang {
  return useSyncExternalStore(
    (f) => {
      subs.add(f);
      return () => subs.delete(f);
    },
    getLang,
    () => "en",
  );
}
export const locale = () => (lang === "hi" ? "hi-IN" : "en-IN");

export function t(s: string, vars?: Record<string, string | number>): string {
  let out = lang === "hi" ? (HI[s] ?? s) : s;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.split(`{${k}}`).join(String(v));
  return out;
}

/** Route notes come from the server in English; translate the known patterns. */
export function tHighlight(text: string): string {
  if (lang !== "hi") return text;
  const and = (s: string) => s.replace(/ and /g, " और ");
  let m: RegExpMatchArray | null;
  if ((m = text.match(/^Passes (.+), about (\d+) min beside greenery$/))) {
    const place = m[1] === "parks and green spaces" ? "पार्क और हरियाली" : and(m[1]);
    return `${place} से होकर, लगभग ${m[2]} मिनट हरियाली के पास`;
  }
  if ((m = text.match(/^Along (.+) for about (\d+) min$/))) {
    const place = m[1] === "a lake or pond" ? "झील या तालाब" : m[1];
    return `लगभग ${m[2]} मिनट ${place} के किनारे`;
  }
  if ((m = text.match(/^(\d+) min (on|beside) busy main roads(?: \((.+)\))?$/))) {
    const where = m[3] ? ` (${and(m[3])})` : "";
    return `${m[1]} मिनट व्यस्त मुख्य सड़कों ${m[2] === "on" ? "पर" : "के पास"}${where}`;
  }
  if (text === "Keeps off busy main roads") return "व्यस्त मुख्य सड़कों से दूर रहता है";
  if (text === "Mostly away from busy main roads") return "ज़्यादातर व्यस्त मुख्य सड़कों से दूर";
  if ((m = text.match(/^Passes near (.+)$/))) {
    return `${m[1] === "an industrial area" ? "एक औद्योगिक इलाके" : m[1]} के पास से गुज़रता है`;
  }
  if (text.startsWith("Near a mapped construction site")) return "निर्माण स्थल के पास (नक्शे की जानकारी पुरानी हो सकती है)";
  return text;
}

const HI: Record<string, string> = {
  // brand and shell
  "Cleaner-air routes across {region}": "{region} में साफ़ हवा वाले रास्ते",
  India: "भारत",
  "Breatheasy can't connect right now. Check your internet connection, then try again.":
    "Breatheasy अभी कनेक्ट नहीं हो पा रहा। अपना इंटरनेट देखें और फिर कोशिश करें।",
  "Your account": "आपका खाता",
  "Sign in": "साइन इन",
  Edit: "बदलें",
  Done: "हो गया",
  Routes: "रास्ते",
  "About this data": "इस डेटा के बारे में",
  "You're offline. Planning will resume when you reconnect.": "आप ऑफ़लाइन हैं। इंटरनेट लौटते ही प्लानिंग फिर शुरू होगी।",
  "Demo mode: routes and air quality are made up.": "डेमो मोड: रास्ते और हवा की जानकारी नकली है।",
  Accuracy: "सटीकता",
  Stats: "आँकड़े",
  Privacy: "गोपनीयता",
  Terms: "शर्तें",

  // search
  Start: "कहाँ से",
  "Where to?": "कहाँ जाना है?",
  "Swap start and destination": "शुरुआत और मंज़िल बदलें",
  "Your location": "आपकी लोकेशन",
  "My location": "मेरी लोकेशन",
  "My location (approximate)": "मेरी लोकेशन (अनुमानित)",
  "This browser can't share your location. Type a place instead.": "यह ब्राउज़र आपकी लोकेशन नहीं बता सकता। कोई जगह टाइप करें।",
  "Location access is off for this site. Allow it in your browser settings, or type a place.":
    "इस साइट के लिए लोकेशन बंद है। ब्राउज़र सेटिंग में अनुमति दें, या कोई जगह टाइप करें।",
  "Couldn't get your location. Type a place instead.": "आपकी लोकेशन नहीं मिल पाई। कोई जगह टाइप करें।",
  "Ask Breatheasy (e.g. reach Hauz Khas by 9 am)": "Breatheasy से अंग्रेज़ी में पूछें (जैसे: reach Hauz Khas by 9 am)",
  Speak: "बोलें",
  "Comparing routes and departure times…": "रास्तों और निकलने के समय की तुलना हो रही है…",
  "That didn't work. Try again in a moment.": "यह नहीं हो पाया। थोड़ी देर में फिर कोशिश करें।",
  "Something didn't work. Try again.": "कुछ गड़बड़ हुई। फिर कोशिश करें।",

  // modes and settings
  Walk: "पैदल",
  Cycle: "साइकिल",
  "Two-wheeler": "दोपहिया",
  "2-wheeler": "दोपहिया",
  Car: "कार",
  "How are you travelling?": "आप कैसे जा रहे हैं?",
  "Cleanest air": "सबसे साफ़ हवा",
  Balanced: "संतुलित",
  Fastest: "सबसे तेज़",
  "The route with the cleanest air, even if it takes longer. Good for runs and unhurried walks.":
    "सबसे साफ़ हवा वाला रास्ता, भले ही थोड़ा ज़्यादा समय लगे। दौड़ने और आराम से टहलने के लिए अच्छा।",
  "Cleaner air, but only a few minutes out of your way.": "साफ़ हवा, पर रास्ते से बस कुछ मिनट ज़्यादा।",
  "The quickest route, with its air quality shown.": "सबसे जल्दी वाला रास्ता, उसकी हवा की जानकारी के साथ।",
  "Route preference": "रास्ते की पसंद",
  "I'm sensitive to pollution": "मुझे प्रदूषण से ज़्यादा तकलीफ़ होती है",
  "Asthma, pregnancy, older age, or travelling with children: stays further from busy roads and pollution spots.":
    "दमा, गर्भावस्था, बढ़ती उम्र या बच्चों के साथ सफ़र: व्यस्त सड़कों और प्रदूषण वाली जगहों से और दूर रखता है।",
  "Any extra time": "कितना भी ज़्यादा समय",
  "No extra time": "कोई अतिरिक्त समय नहीं",
  "Up to {n} min longer": "{n} मिनट तक ज़्यादा",
  "Leave now": "अभी निकलें",
  "Leave later": "बाद में निकलें",
  "Departure time": "निकलने का समय",
  "How much longer would you travel for cleaner air?": "साफ़ हवा के लिए आप कितना ज़्यादा समय लगाएँगे?",
  "Any extra time: show me the cleanest air, however long": "कितना भी समय: सबसे साफ़ हवा दिखाएँ, चाहे जितना लगे",
  "Later departures use the hourly air-quality forecast.": "बाद के समय के लिए हर घंटे का हवा का पूर्वानुमान इस्तेमाल होता है।",
  " · any time": " · कितना भी समय",
  " · no extra time": " · कोई अतिरिक्त समय नहीं",

  // loading and results
  "Finding routes": "रास्ते ढूँढ रहे हैं",
  "Checking the air along each route": "हर रास्ते की हवा जाँच रहे हैं",
  "Comparing exposure on each route": "हर रास्ते पर प्रदूषण की तुलना कर रहे हैं",
  "Long trip, still checking. Almost there": "लंबा सफ़र है, अभी जाँच जारी है। बस हो गया",
  "Where are you heading?": "आप कहाँ जा रहे हैं?",
  "Enter a start and destination. We'll compare the routes and show which one has cleaner air, and how much time it costs.":
    "शुरुआत और मंज़िल डालें। हम रास्तों की तुलना करके बताएँगे कि किसमें हवा साफ़ है, और उसमें कितना समय लगेगा।",
  "Sign in to save places and keep a trip log": "जगहें सेव करने और सफ़र का रिकॉर्ड रखने के लिए साइन इन करें",
  "Cleaner air, {n} min longer": "साफ़ हवा, {n} मिनट ज़्यादा",
  "Cleaner air, no extra time": "साफ़ हवा, बिना अतिरिक्त समय",
  "Average PM2.5 {a} µg/m³ instead of {b} on the fastest route": "औसत PM2.5 {a} µg/m³, सबसे तेज़ रास्ते पर {b} की जगह",
  " (AQI {a} vs {b}).": " (AQI {a} बनाम {b})।",
  " It goes via {via}.": " यह {via} से होकर जाता है।",
  "Air is similar on every route": "हर रास्ते पर हवा लगभग एक जैसी है",
  "Fastest route": "सबसे तेज़ रास्ता",
  "Around {pm} µg/m³ PM2.5 (AQI {aqi}, {label}) whichever way you go, so take the quickest.":
    "किसी भी रास्ते से जाएँ, PM2.5 लगभग {pm} µg/m³ (AQI {aqi}, {label}) है, इसलिए सबसे जल्दी वाला रास्ता लें।",
  "Worth {n} extra minutes": "{n} मिनट ज़्यादा लगाना फ़ायदेमंद",
  "Less pollution, no extra time": "कम प्रदूषण, बिना अतिरिक्त समय",
  "Take the fastest route": "सबसे तेज़ रास्ता लें",
  "You'd breathe about {n}% less pollution than on the fastest route.": "सबसे तेज़ रास्ते की तुलना में आप लगभग {n}% कम प्रदूषण साँस में लेंगे।",
  " Current conditions as of {t}.": " मौजूदा स्थिति {t} तक की।",
  " Later parts of the trip use the hourly forecast.": " सफ़र के बाद के हिस्से के लिए हर घंटे का पूर्वानुमान इस्तेमाल होता है।",
  "Pollution spots are the stretches of a route with the highest PM2.5. Air-quality guidance here is general information, not medical advice.":
    "प्रदूषण वाली जगहें रास्ते के वे हिस्से हैं जहाँ PM2.5 सबसे ज़्यादा है। यहाँ दी गई जानकारी सामान्य है, चिकित्सा सलाह नहीं।",
  "Google Maps follows these same streets, using a few pins it shows as stops (just pass through them). Its time can differ by a few minutes because it uses live traffic.":
    "Google Maps इन्हीं सड़कों पर चलता है, कुछ पिन के सहारे जिन्हें वह स्टॉप दिखाता है (बस उनसे होकर निकल जाएँ)। लाइव ट्रैफ़िक के कारण उसका समय कुछ मिनट अलग हो सकता है।",
  "Data sources and cost": "डेटा स्रोत और खर्च",
  "Download trip data": "सफ़र का डेटा डाउनलोड करें",
  "Go by {mode}": "{mode} से जाएँ",
  "Change start point": "शुरुआत की जगह बदलें",
  "Try again": "फिर कोशिश करें",
  "Thanks, that helps.": "धन्यवाद, इससे मदद मिलती है।",
  "Trip added to your log": "सफ़र आपके रिकॉर्ड में जुड़ गया",
  "This trip couldn't be added to your log": "यह सफ़र आपके रिकॉर्ड में नहीं जुड़ पाया",
  "Added to your trip log.": "आपके सफ़र रिकॉर्ड में जुड़ गया।",
  "We'll add this trip to your log.": "हम यह सफ़र आपके रिकॉर्ड में जोड़ देंगे।",
  "Link copied. Paste it in WhatsApp or anywhere.": "लिंक कॉपी हो गया। WhatsApp या कहीं भी पेस्ट करें।",
  "my destination": "मेरी मंज़िल",
  "My cleaner-air route to {to}: {n} min": "{to} तक मेरा साफ़ हवा वाला रास्ता: {n} मिनट",
  ", average PM2.5 {pm} µg/m³": ", औसत PM2.5 {pm} µg/m³",
  " (fastest route: {pm})": " (सबसे तेज़ रास्ता: {pm})",
  ". Plan yours on Breatheasy:": "। अपना रास्ता Breatheasy पर देखें:",
  "Would you take that route again?": "क्या आप वह रास्ता फिर से लेंगे?",
  Yes: "हाँ",
  No: "नहीं",
  Dismiss: "बंद करें",

  // route card
  Recommended: "सुझाया गया",
  "Longer than your limit": "आपकी सीमा से लंबा",
  "Via {via}": "{via} से होकर",
  "Through green space": "हरियाली से होकर",
  "Main route": "मुख्य रास्ता",
  "Alternative route": "दूसरा रास्ता",
  "Side-street route": "गलियों वाला रास्ता",
  "Arrive {t}": "{t} पहुँचें",
  "About the same air as the fastest route": "हवा लगभग सबसे तेज़ रास्ते जैसी",
  "{n} µg/m³ cleaner than the fastest route": "सबसे तेज़ रास्ते से {n} µg/m³ साफ़",
  "{n} µg/m³ dirtier than the fastest route": "सबसे तेज़ रास्ते से {n} µg/m³ ज़्यादा प्रदूषित",
  "Avg PM2.5 · µg/m³": "औसत PM2.5 · µg/m³",
  "Avg AQI · {label}": "औसत AQI · {label}",
  "{n} min": "{n} मिनट",
  "{h} h {m} min": "{h} घंटे {m} मिनट",
  " in ": " ",
  "{n} min in {label}": "{n} मिनट {label} में",
  "(above {level} µg/m³)": "({level} µg/m³ से ऊपर)",
  " · fastest route {n} min": " · सबसे तेज़ रास्ता {n} मिनट",
  "You pass through": "रास्ते में",
  "{n} pollution spots on the way, worst {w} µg/m³ (marked on the map)": "रास्ते में {n} प्रदूषण वाली जगहें, सबसे ख़राब {w} µg/m³ (नक्शे पर दिखाई गई)",
  "1 pollution spot on the way, worst {w} µg/m³ (marked on the map)": "रास्ते में 1 प्रदूषण वाली जगह, {w} µg/m³ (नक्शे पर दिखाई गई)",
  "Air-quality data covered {n}% of this route.": "इस रास्ते के {n}% हिस्से का हवा डेटा मिला।",
  "Start in Google Maps": "Google Maps में शुरू करें",
  Share: "शेयर करें",
  "Share this route": "यह रास्ता शेयर करें",

  // air labels (CPCB)
  Good: "अच्छी",
  Satisfactory: "संतोषजनक",
  Moderate: "मध्यम",
  Poor: "ख़राब",
  "Very poor": "बहुत ख़राब",
  Severe: "गंभीर",
  "No data": "डेटा नहीं",
  "poor air": "ख़राब हवा",
  "very poor air": "बहुत ख़राब हवा",
  "severe air": "गंभीर हवा",

  // legend
  "The map is coloured by PM2.5: the weight of fine dust and smoke particles in one cubic metre of air, in micrograms (µg/m³). India's safe limit is {limit} (WHO's is 15), so anything orange or red is above it. The AQI number on each route is the overall air-quality score built from PM2.5 and other pollutants.":
    "नक्शे के रंग PM2.5 दिखाते हैं: एक घन मीटर हवा में धूल और धुएँ के बारीक कणों का वज़न, माइक्रोग्राम (µg/m³) में। भारत की सुरक्षित सीमा {limit} है (WHO की 15), इसलिए नारंगी या लाल इससे ऊपर है। हर रास्ते पर AQI, PM2.5 और दूसरे प्रदूषकों से बना कुल हवा का स्कोर है।",

  // best time
  "Best time to leave": "निकलने का सबसे अच्छा समय",
  "Leaving now is about as clean as it gets in the next 2 hours.": "अगले 2 घंटों में अभी निकलना ही लगभग सबसे साफ़ है।",
  "Leave at {t} for about {n}% cleaner air on this route.": "{t} बजे निकलें, इस रास्ते पर लगभग {n}% साफ़ हवा मिलेगी।",
  Now: "अभी",
  "Leaving now": "अभी निकलना",
  "Plan this trip leaving at {t}": "{t} बजे निकलने पर यह सफ़र देखें",
  "Average PM2.5 (µg/m³) on this route by departure time, from the hourly forecast":
    "निकलने के समय के हिसाब से इस रास्ते पर औसत PM2.5 (µg/m³), हर घंटे के पूर्वानुमान से",
};
