# SkillSwap — MVP Scope and Product Decisions

**Status:** Initial product scope  
**Working name:** SkillSwap (can be changed later)  
**Product type:** Responsive web platform for exchanging skills using points  
**Primary goal:** Help people teach skills they know and learn skills they need without paying real money for points.

---

## 1. Product concept

SkillSwap is an online platform where anyone can share what they know and learn from others. Users can teach live online sessions or publish self-paced learning materials. Teaching earns points, and users spend points to access other people's lessons and materials.

Users have one account and one profile for both teaching and learning.

## 2. Decisions made during brainstorming

### Audience and exchange model

- **Audience:** Anyone who wants to exchange skills.
- **Exchange model:** Points-based skill exchange.
- **Teaching formats:** Scheduled live online sessions and self-paced materials.
- **Live sessions:** Teachers share external meeting links, such as Google Meet or Zoom.
- **Learning materials:** Users upload PDFs, presentations, videos, and exercises directly to the platform.
- **Skill categories:** All categories, including programming, languages, design, music, cooking, and business.
- **Learning paths:** Postponed until after the MVP.

### Accounts and profiles

- Users can register and log in with email/password or Google sign-in.
- Each person has one account and can both teach and learn.
- Profiles include detailed information, ratings, reviews, projects, certificates, and teaching materials.
- Certificates and projects should be optional rather than required for every user.

### Finding skills and teachers

- Users can search and filter skills and materials.
- The platform also provides personalized recommendations.
- A skill listing displays:
  - Skill level
  - Learning outcomes
  - Lesson duration
  - Materials preview
  - Teacher rating
  - Point cost
- The homepage combines:
  - Search
  - Personalized recommendations
  - Points balance
  - Community activity
- Users can follow teachers and see their new lessons in the community feed.

### Points and access

- Users receive free starter points.
- Users earn more points by teaching.
- Points cannot be purchased with real money.
- A completed live lesson earns the teacher a fixed number of points; **10 points per lesson** is the initial example.
- Recorded materials cost fewer points than live sessions.
- Users spend points for instant access to recorded lessons/materials.
- The proposed initial recorded-material price is **2–5 points**, to be tested.
- When a learner books a live session, points are reserved.
- Reserved points transfer to the teacher after both participants confirm completion.
- If the learner does not attend, the current proposed rule is to return the reserved points to the learner.
- If the teacher and learner disagree about completion, points remain reserved until an administrator reviews the case.
- Cancellation rules provide free cancellation before a deadline; late cancellations may affect points or reputation.

### Messaging and scheduling

- The platform supports private messaging.
- Users can book and schedule live sessions.
- Teachers manage their availability.
- Bookings include a date, start time, duration, and external meeting link.
- Both participants receive important booking updates and reminders.

### Quality and trust

- Users can rate lessons and leave reviews.
- Users can report inappropriate or misleading content.
- Users can block or mute other users.
- Ratings should be linked to genuine completed interactions where applicable.
- The platform needs an admin workflow for reports and disputes.

### Progress and notifications

- Users can mark learning materials as completed.
- Users can view their learning history.
- Notifications are provided in-app and by email for important messages, bookings, points, and reviews.
- Users should be able to control or mute non-essential notifications.

## 3. Recommended decisions and reasoning

These are proposed defaults, not immutable requirements. They should be tested with users.

### Decision 1: Keep the point economy simple

**Recommendation**
- Give new users a modest starter balance.
- Use fixed rewards for completed live lessons.
- Use a small allowed price range for recorded materials.
- Do not allow point purchases.
- Record every point movement in a transaction ledger.

**Initial example values**
- Starter points: **20** (proposed; test before finalizing).
- Live lesson reward: **10 points** (the example selected during brainstorming).
- Recorded material: **2–5 points** (proposed starting range).

**Why:** The system should be understandable, give new users a way to try the platform, and encourage teaching without introducing money payments.

**Alternatives considered**
- Teachers choose any price: flexible, but may lead to confusing or inconsistent prices.
- Unlimited free points: easy for learners, but weakens the incentive to teach.
- Paid points or subscriptions: add payment complexity and change the no-purchase model.

**Important design note:** Track points as transactions and maintain a clear balance. Avoid accidental duplicate rewards. The rules should define how points are created, reserved, transferred, and returned. Since points are not purchasable, the system still needs a carefully tested issuance policy to avoid runaway inflation.

### Decision 2: Make recorded-resource access convenient

**Recommendation:** A user pays once to unlock a resource and can access it again from their learning library.

**Why:** Charging every time someone opens a PDF or video would discourage revision and repeat learning.

**Alternatives considered**
- Charge every time: discourages review.
- Make every resource free: offers less incentive to create useful materials.
- Subscription access: adds unnecessary complexity for the MVP.

Creators should add a title, description, category, skill level, preview, and point price. Define whether access is permanent and what happens if a resource is removed or an account is suspended.

### Decision 3: Use structured booking

**Recommendation:** Each live session has a date, start time, duration, external meeting link, and booking status. Teachers manage availability, and learners select an available time slot.

**Why:** Structured booking reduces scheduling conflicts and makes the experience easier to understand.

**Alternatives considered**
- Arrange everything in chat: easy to build, but details can get lost.
- Allow booking at any time: can create schedule conflicts.
- Build video calls into the platform: adds technical complexity when external links are sufficient.

Send reminders to both participants. Avoid exposing meeting links to people who are not authorized to attend.

### Decision 4: Define completion, cancellation, and dispute states

**Recommendation**
1. Reserve points when a live session is booked.
2. Both participants confirm completion.
3. Transfer reserved points after both confirm.
4. Return points for cancellation within the free-cancellation window.
5. If a completion dispute is reported, keep points reserved for admin review.
6. Keep a record of status changes and decisions.

**Why:** These rules are intended to protect both participants.

**Alternatives considered**
- Trust only the teacher: unfair to learners.
- Trust only the learner: unfair to teachers.
- Automatically refund every disagreement: may encourage dishonest claims.

**Unresolved rule:** Decide what happens when only one participant confirms completion and the other never responds. Define a response deadline and a fair escalation process rather than transferring or refunding points silently.

**Unresolved cancellation details:** Choose the free-cancellation deadline, what qualifies as a late cancellation, how no-shows are established, and whether reputation penalties apply. Make the rules visible before booking.

### Decision 5: Use one profile for both roles

**Recommendation:** Each profile includes “Skills I Teach” and “Skills I Want to Learn,” alongside a bio, languages, skill levels, projects, certificates, materials, ratings, and reviews.

**Why:** A person can teach one skill and learn another. One profile avoids duplicated information.

**Alternatives considered**
- Separate teacher and learner accounts: duplicate information and complicate registration.
- Minimal profiles: less work, but provide less information for choosing a teacher.
- Require certificates for every skill: creates unnecessary barriers for informal skills.

Projects and certificates should be optional. Ratings should be based on real interactions rather than unrestricted self-reported reviews.

### Decision 6: Start with rule-based recommendations

**Recommendation:** Use search, filters, and simple recommendations based on users' interests, skill levels, languages, followed teachers, and relevant lesson attributes. Do not build AI recommendations for the MVP.

**Why:** Basic recommendations are useful without needing training data or a complex model.

**Alternatives considered**
- Search only: simpler, but less personalized.
- AI recommendations: potentially valuable later, but require more data and development.
- Show only popular lessons: can make it difficult for new creators to be discovered.

### Decision 7: Keep community features focused

**Recommendation:** Include private text chat, following, a simple community feed, and notifications.

- The feed highlights new lessons from followed teachers and selected community activity.
- Chat supports text and sharing lesson links.
- Notifications cover messages, bookings, point transactions, and reviews.
- Users can mute notifications and block or report others.

**Why:** These features support learning relationships without turning the MVP into a full social network.

**Alternatives considered**
- No chat: forces users to communicate elsewhere.
- Public messaging: increases spam and privacy risks.
- Forums, groups, public comments, and extensive social features: expand scope without proving the core exchange works.

### Decision 8: Add basic upload safeguards

**Recommendation:** Support PDFs, presentations, videos, and exercises with file-size limits, allowed file types, and security checks where feasible.

Each resource should include a title, description, category, skill level, preview, and point cost.

**Why:** Structured resources are easier to find and compare than unlabelled files.

**Alternatives considered**
- External links only: simpler, but less consistent.
- Unlimited file types and sizes: increases storage and security risks.
- Manually approve every upload: creates delays and administrative workload.

Uploaded files should not be publicly accessible just because someone knows a file URL. Use access checks for paid/unlocked materials, and provide reporting and removal tools.

### Decision 9: Build a small admin panel

**Recommendation:** Admins can:
- Review reported users and materials.
- Investigate booking disputes.
- Resolve reserved-point transactions.
- Remove inappropriate content and suspend abusive accounts.
- View basic platform activity.

**Why:** The dispute and reporting policies require someone authorized to act.

**Alternatives considered**
- No admin tools: disputes cannot be resolved consistently.
- Advanced moderation analytics: excessive for an MVP.
- Automatic resolution of every dispute: cannot handle every situation fairly.

### Decision 10: Use established authentication and privacy practices

**Recommendation**
- Support email/password and Google sign-in.
- Verify email addresses.
- Use a trusted authentication library or provider rather than building authentication from scratch.
- Protect private messages and personal information with access controls.
- Provide account deletion, subject to necessary transaction records and applicable requirements.
- Allow users to block and report others.

**Why:** Users need to trust the platform before sharing content or communicating with strangers.

**Alternatives considered**
- Custom authentication from scratch: more risk and work.
- Make every profile and upload public: easier to discover, but weakens privacy.
- Require extensive identity verification: adds friction and is not necessary for the initial version.

### Decision 11: Build a responsive web app first

**Recommendation:** Start with one responsive web application that works on desktop, tablet, and mobile. Use a relational database for users, lessons, bookings, point transactions, reviews, and reports.

**Why:** One web application is easier to develop, test, and maintain than separate native mobile apps.

**Alternatives considered**
- Native iOS and Android apps: useful later, but more work.
- Desktop-only website: simpler, but limits access.
- Microservices: often unnecessary complexity for an early-stage project.

Choose the specific frontend, backend, database, and file-storage technology after clarifying the team's skills and project requirements.

## 4. MVP feature checklist

### Accounts and profiles
- [ ] Email/password registration and login
- [ ] Google sign-in
- [ ] One profile for teaching and learning
- [ ] Bio, languages, skill levels, projects, certificates
- [ ] Skills to teach and skills to learn

### Discovery and content
- [ ] Homepage with search, recommendations, point balance, and community activity
- [ ] Search and filters
- [ ] All skill categories, including programming, languages, design, music, cooking, and business
- [ ] Lesson listings with level, outcomes, duration, preview, rating, and point cost
- [ ] Upload PDFs, presentations, videos, and exercises
- [ ] Unlock recorded materials with points
- [ ] Learning library and completion history
- [ ] Follow teachers and view their new lessons

### Points and live sessions
- [ ] Starter points
- [ ] Fixed teaching reward for completed live lessons
- [ ] Recorded materials cost fewer points than live sessions
- [ ] Point transaction ledger
- [ ] Reserve points at booking
- [ ] Teacher availability and session scheduling
- [ ] External meeting links
- [ ] Both users confirm completion
- [ ] Cancellation rules and no-show handling
- [ ] Dispute handling and admin review

### Community and trust
- [ ] Private chat
- [ ] Ratings and reviews
- [ ] Report and block users
- [ ] Report content
- [ ] In-app notifications
- [ ] Email notifications
- [ ] Basic admin panel

## 5. Explicitly postponed features

Do not build these into the first release unless testing reveals a strong need:

- Learning paths and structured course sequences
- AI-powered recommendations
- Built-in video calls
- Platform-issued certificates
- Paid points and subscriptions
- Group lessons and group chats
- Badges, streaks, and leaderboards
- Dedicated native mobile apps
- Advanced analytics
- Public forums and complex social features

**Reason:** The first release should test the core assumption: will people teach others to earn points and spend those points to learn?

## 6. Suggested user flows

### A. New user joins
1. Register with email/password or Google.
2. Create a profile and select skills to teach and learn.
3. Receive starter points.
4. Browse or search for skills.
5. Unlock a recorded resource or book a live session.

### B. User publishes a recorded resource
1. Choose a skill category and level.
2. Add title, description, learning outcomes, preview, and point price.
3. Upload the resource.
4. The system validates the file and publishes the listing, subject to moderation/reporting rules.
5. Another user spends points to unlock it.
6. The resource appears in the learner's library.

### C. User books a live lesson
1. Find a teacher and review the listing.
2. Choose an available time slot.
3. Review cancellation rules.
4. Confirm booking; reserve the required points.
5. Receive the meeting link and reminders.
6. Attend the external video call.
7. Both participants confirm completion.
8. Transfer reserved points to the teacher and enable a review.

### D. A session is disputed
1. One participant reports a problem.
2. Keep the reserved points on hold.
3. Let both participants provide relevant details.
4. An admin reviews the case.
5. Record the decision and apply the appropriate point transaction.

## 7. Key unresolved questions

Resolve these before implementation:

1. **Point economy:** Confirm starter points, teaching rewards, material prices, and point issuance safeguards.
2. **Completion and cancellation:** Set exact deadlines, response periods, late-cancellation consequences, and no-show rules.
3. **Technology and constraints:** Choose the stack based on team experience, deadline, and whether the goal is a university project or a public launch.
4. **File limits:** Define maximum upload size, supported video formats, storage budget, and access rules.
5. **Moderation:** Decide who will serve as admin and how quickly reports should be reviewed.
6. **Privacy and terms:** Define profile visibility, data retention, deletion, content ownership, and community rules.

## 8. Recommended next steps

1. Confirm the point economy and booking state rules.
2. Draw user-flow diagrams for registration, unlocking material, booking a lesson, and dispute handling.
3. Create a database model for users, skills, listings, materials, point transactions, bookings, reviews, reports, and notifications.
4. Sketch the main screens: homepage, profile, search results, skill listing, learning library, booking page, chat, and admin panel.
5. Select the technology stack.
6. Implement the core flows before adding polish or advanced recommendations.
7. Test with a small group of users and adjust the point values and policies based on their behavior.

---

## Product principle

**Keep the first release simple enough to build, but complete enough for real people to use.** Prioritize a trustworthy point system, clear lesson listings, reliable booking, and a fair dispute process over advanced features.
