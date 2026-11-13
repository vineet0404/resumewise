/* Terms, Privacy and FAQ texts. English only.
   DRAFT: written to match what the app really does today. A lawyer must check the Terms and the
   Privacy Policy (company name, address, governing law, data-protection duties) before public launch.
   Fill the three values in LEGAL.owner. */
window.LEGAL = {
  owner: { name: "[Your name or company]", email: "[support email]", place: "[City, India]", updated: "2026-11-13" },
  draft: "Draft for review. This text has not been checked by a lawyer yet.",
  terms: {
    title: "Terms of Use",
    intro: "These terms are the rules for using ResumeWise. By creating an account you agree to them.",
    sections: [
      ["Who we are", ["ResumeWise is a tool that helps you build a CV and fit it to a job. It is run by the owner named at the bottom of this page."]],
      ["Your account", [
        "You must give a real email address and keep your password and login methods safe. You are responsible for what happens in your account.",
        "You must be 16 or older, or have a parent or guardian agree for you."]],
      ["Your CV and your content", [
        "Your CV, jobs, notes and answers belong to you. We use them only to give you the service.",
        "You promise that what you put in your CV is true. ResumeWise does not check facts, and you are responsible for every line you send to an employer."]],
      ["What the tool does and does not do", [
        "The tool rewords and organises what you wrote. It never invents skills, jobs or numbers, and the AI part marks anything that is not already in your CV so you can accept or remove it.",
        "Scores such as the match score and the scanner check are our own simple checks. They are not a real company's system, and they do not promise a job, an interview or a shortlist."]],
      ["Rules", [
        "Do not use the service to put false information in a CV, to attack or overload the site, to try other people's accounts, or to break the law.",
        "We may limit or stop an account that breaks these rules or harms other people or the service."]],
      ["Paid plans", [
        "Some limits (for example AI runs per day and saved jobs) are higher on a paid Pro pass. A Pro pass lasts for the number of days you buy and does not renew by itself.",
        "You pay on the secure page of our payment provider, Razorpay. We never see or store your card, UPI or bank details.",
        "Prices are shown in rupees before you pay. Refunds are explained in the Refund and Cancellation page."]],
      ["Limits and changes", [
        "We use limits (for example on sign-ups, AI use and uploads) to keep the service fair and affordable. They can change.",
        "The service is provided as it is, without a guarantee that it will always work or be free of mistakes. As far as the law allows, we are not responsible for lost job chances or other indirect loss.",
        "We may change these terms. For big changes we will tell you in the app."]],
      ["Ending", ["You can delete your account any time in the Account tab. We may close accounts that break the rules."]],
      ["Law and contact", ["Indian law applies, and the courts of the place named below can decide disputes, unless the law gives you other rights. Questions: write to the email below."]]
    ]
  },
  privacy: {
    title: "Privacy Policy",
    intro: "This says what we keep about you, why, for how long, and who else sees it. We do not sell your data and we do not show ads.",
    sections: [
      ["What we keep", [
        "Account: your name, email address, and a scrambled (hashed) password. If you use two-step login or passkeys, the secrets needed for that (stored safely, never shown back).",
        "Your CV as text, its earlier versions, your template choice, and your photo if you add one (location and camera data are removed from the photo).",
        "Share link (only if you create one): a secret web address for your CV and the options you chose. We count how many times it was opened, nothing else.",
        "Jobs you save: title, company, link, the job text you pasted, your status, follow-up day, notes and interview answers.",
        "AI tailoring results and what each run cost.",
        "Feedback you send with the feedback button.",
        "Technical records: login and session cookies, and short error records (page, type of error, a short message, never what you typed)."]],
      ["Why we keep it", ["To run the service for you: sign you in, show your CV, check it against a job, tell you when to follow up, keep the site safe, and fix errors."]],
      ["How long", [
        "CVs, their versions, photos, jobs and tailoring results are deleted automatically 30 days after you last work on them. You can delete them yourself at any time.",
        "Your account stays until you delete it. Deleting it removes everything above, including feedback.",
        "Payment records (date, amount, plan, payment id) are kept for accounting and tax even after you delete your account; they are then no longer linked to your name or email.",
        "Error records are kept for 30 days. Login links and similar one-time codes expire within hours."]],
      ["Who else gets data", [
        "Share link: if you turn it on, anyone who has the address can read your CV (email, phone and photo only if you ticked them). Do not post the address anywhere you do not want the CV to be seen. Turn it off in the Templates tab at any time.",
        "AI tailoring (only when you press the button): the numbered lines of your CV and the job text are sent to our AI provider (Anthropic). Your name, contact details and photo are not sent.",
        "Email: reminder, login and confirmation emails go through our email provider.",
        "Payments: if you buy a Pro pass, Razorpay receives your name and email and handles your payment. We receive only the result (paid or not, amount, a payment id).",
        "Hosting: the site runs on a hosting provider's servers.",
        "If you sign in with Google or LinkedIn, they tell us your name and email.",
        "We share data with the authorities only if the law requires it."]],
      ["Cookies", ["We use cookies only to keep you signed in and to protect forms. We do not use advertising or tracking cookies."]],
      ["Your choices", [
        "Download everything we keep about you (Account tab > Download my data).",
        "Edit any CV line, delete a CV or a job, switch off reminder emails per job, or delete your whole account at any time.",
        "You can also ask us to correct or delete your data by writing to the email below. Indian law, including the Digital Personal Data Protection Act, 2023, gives you rights over your personal data; we will answer within a reasonable time."]],
      ["Safety", ["Passwords are hashed, pages are served with strict security headers, and other people cannot open your CV. No system is perfectly safe; if something goes wrong that affects you, we will tell you."]],
      ["Changes and contact", ["If we change this policy in an important way we will tell you in the app. Questions or requests: write to the email below."]]
    ]
  },
  refunds: {
    title: "Refund and Cancellation",
    intro: "Pro is a pass for a fixed number of days. It does not renew by itself, so there is nothing to cancel. [Owner: confirm these rules before launch.]",
    sections: [
      ["Refund", [
        "If you are not happy, write to us within 7 days of paying and we will refund the full amount, as long as you have used fewer than 3 AI tailoring runs on the pass.",
        "Refunds go back to the payment method you used, usually within 5 to 7 working days. When a refund is made, the days of that pass are removed from your account."]],
      ["If you paid but Pro did not start", ["Wait a few minutes and reload the Account tab. If it still shows the free plan, write to us with the email you used and the payment id from your Razorpay receipt, and we will fix it or refund you."]],
      ["Free plan", ["Building, editing and downloading your CV stays free."]],
      ["Contact", ["Write to the email below. We answer within 2 working days."]]
    ]
  },
  faq: {
    title: "Questions and answers",
    intro: "Short answers to what people ask most.",
    items: [
      ["Is it free?", "You can try everything now. If paid plans come later, the free part for building and downloading a CV will stay."],
      ["Does it invent things in my CV?", "No. It only uses your own lines. The AI part may reword them, and anything that is not in your CV is marked so you can confirm it (only if true) or remove it before download."],
      ["Who can see my CV?", "Only you, unless you create a share link (see below). We do not show it to employers or other users. The owner's dashboard shows numbers only, not CV text."],
      ["What happens to my CV after 30 days?", "It is deleted automatically. Download or print it before that, or just keep using the app: working on it keeps it longer."],
      ["Can other people see my CV through a share link?", "Only if you create a share link. Then anyone who has the secret address can read it. Email, phone and photo stay hidden unless you tick them. You can turn the link off at any time in the Templates tab."],
      ["Is my data sent to an AI?", "Only if you press the AI tailoring button. Then the numbered CV lines and the job text are sent, without your name, contact details or photo."],
      ["How do I delete everything?", "Account tab > Delete my account. It removes your account, CVs, jobs, results and feedback for good."],
      ["How do I get my data?", "Account tab > Download my data gives you one file with everything we keep."],
      ["My scanned PDF was read with mistakes.", "Scans are read by OCR, which can make mistakes with numbers, names and dates. Check every line, or upload a Word file or paste the text."],
      ["What is the match score?", "It counts how many words from the job description really appear in your CV lines. It is our own simple check, not a real company's system."],
      ["How do follow-up reminders work?", "When you mark a job as applied, we suggest a follow-up day 7 days later. You change the day in the Jobs tab. We email you once on that day if your email is confirmed. You can switch the email off for a job."],
      ["I did not get an email.", "Check spam. Confirm your email from the banner at the top of the app. If it still fails, send feedback from the Help tab."],
      ["How do I pay, and is it safe?", "Account tab > pick a Pro pass. You pay on Razorpay's own page with UPI, card or net banking. We never see your card or UPI details. The pass does not renew by itself."],
      ["I paid but still see the free plan.", "Wait a few minutes and reload. If it does not change, write to us with your payment id (see Refund and Cancellation)."],
      ["Which languages work?", "The screens are in English, Hindi, Marathi and Telugu (pick one at the top). Your CV stays in the language you wrote it."],
      ["I found a mistake or have an idea.", "Use Send feedback in the Help tab. We read every message."]
    ]
  }
};
