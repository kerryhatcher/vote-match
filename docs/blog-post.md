# 1,035 Voters in the Wrong District: How I Built a Tool to Check

Imagine showing up to vote and being told you're in the wrong district. Not because you moved. Not because you filled out a form incorrectly. Because somewhere between the maps and the voter rolls, the system put you in the wrong place.

That's not a hypothetical. Right now, **at least 1,035 voters in Macon-Bibb County are registered in a commission district that doesn't match where they actually live**. And with a special election for District 5 coming up on March 17th, that's a problem we need to talk about.

I want to tell you how I found this, why it matters, and what you can do about it.

## It Started at a Commission Meeting

On January 20, 2026, the Macon-Bibb County Commission met to vote on a resolution scheduling a special election. The election would fill the unexpired term of Seth Clark, who had represented District 5. The vote was set for March 17th.

The resolution passed 6-1. Commissioner Donice Bryant cast the lone dissenting vote. Among her concerns: **the accuracy of the county's district maps**. Were voters actually assigned to the right districts?

I'm a software engineer and a Macon-Bibb County resident. When I heard Commissioner Bryant's concerns, something clicked. The voter registration data is public. The district boundary maps are public. I had the skills to compare the two. So I did.

## This Isn't New

Before I get into the technical details, I want you to hear from someone who has lived this problem firsthand.

A local civic organizer I spoke with -- someone with a background in politics and deep roots in Macon's civic life -- told me this has been happening for years. He experienced it himself.

"We had people voting that was showing up in the wrong district," he told me. "Half myself included. Showed up and I was in the old district."

He wasn't alone. It got serious enough that he ended up getting voter protection involved. "They came down from Atlanta," he said.

According to him, this kind of thing is common when district maps get redrawn. But in Macon-Bibb, the problem was compounded. "What made it much worse was that the county got hacked," he explained. At one point, only a single computer had access to JARVIS, the voting system.

When I shared my findings -- 1,035 voters in the wrong district -- his response was blunt: **"It's wild that's still the case years later."**

Years later. And a special election weeks away.

## The Numbers

Here's what the analysis found:

- **1,035 voters** across all 9 county commission districts are registered in a district that doesn't match where they actually live, according to Macon-Bibb County's own GIS boundary maps.
- **540 of those voters are in District 5** -- the very district with the upcoming special election.
- As the analysis expanded from District 5 to all 9 districts, the number nearly doubled.

These are **conservative numbers**. I only counted voters whose addresses could be matched to coordinates with high confidence. The real number is likely higher.

I also want to be upfront about the limits of this analysis. The primary geocoding source I used is the US Census Bureau's geocoder -- an official government service, but not a perfect one. Geocoding can occasionally place an address slightly off from its true location, especially near district boundaries. Some of the mismatches I found could be the result of geocoding imprecision rather than a genuine registration error.

**My findings should not be taken as gospel truth.** What they should be taken as is a strong signal that something warrants a closer look. The right next step isn't to accept my numbers at face value -- it's to call for a **professional, independent third-party audit** of voter-district assignments to make sure no one is being left out of an election they should be voting in.

I also want to be clear: **none of these voters did anything wrong.** They registered to vote. They were assigned a district. That assignment was incorrect. Most of them probably don't even know.

## How Do You Even Check Something Like This?

The core idea is simple. Every voter has two pieces of information that should agree:

1. **What the state says**: the district listed on their voter registration (from the Georgia Secretary of State)
2. **What the map says**: the district their address physically falls inside (from the county's GIS boundary maps)

If those two don't match, there's a problem. Think of it like a phone book that says you live on Oak Street, but your house is actually on Elm Street. Except instead of a street name, it's which commissioner represents you.

Here's how I checked:

1. **Got the voter list.** The Georgia Secretary of State publishes voter registration data. Each record includes the voter's name, address, and their assigned districts -- county commission, congressional, state senate, state house, and more.

2. **Got the map.** Macon-Bibb County publishes its commission district boundaries through its GIS system. These are the official lines that define where each of the 9 districts begins and ends.

3. **Turned addresses into dots on a map.** This is called geocoding -- converting a street address like "123 Main St" into GPS coordinates. I used multiple services, starting with the free US Census geocoder and falling back to others for addresses that didn't match the first time.

4. **Put everything in a spatial database.** I loaded both the voter coordinates and the district boundary shapes into PostGIS, a database that understands geography. It can answer questions like "which shape does this point fall inside?"

5. **Asked the question.** For each voter, I asked the database: which district polygon contains this voter's address? That gives the voter's *actual* district according to the map.

6. **Compared.** Registered district vs. actual district. Any mismatch gets flagged.

I built this tool -- called **Vote Match** -- over 4 days in early February 2026. Sixty-eight commits. The entire codebase is open source under the AGPL-3.0 license, published on [GitHub](https://github.com/kerryhatcher/vote-match). Every step of the methodology is documented and reproducible.

The data is public. The tools are free or cheap. The question is simple. It just took someone asking it.

## The Maps Tell the Story

I could throw more numbers at you, but the maps make this instantly clear.

Each voter is shown as a colored dot -- the color represents the district they're *registered* in according to the Secretary of State. The background shading shows the *actual* district boundaries from the county's GIS maps. When a dot's color doesn't match the region it sits in, that voter is in the wrong district.

![All 1,035 mismatched voters across Macon-Bibb County's 9 commission districts](District%205%20Errors.webp)

Zoom into District 5 and the problem jumps off the screen. Clusters of voters registered in District 5 are sitting clearly outside its boundaries, in neighborhoods that belong to neighboring districts.

![District 5 detail showing mismatched voters](District%205%20Errors_2.webp)

I shared these maps, along with the underlying data in CSV format, directly with county officials. An [interactive version of the map](https://maps.kerryhatcher.com/304rhjgh02u6667gskrsdthjw84rgh/mbc.html) lets you zoom in, click individual markers, and explore the data yourself.

## March 17th Is Coming

The special election for District 5 is March 17, 2026. That's not far away.

If 540 or more voters in District 5 are registered in the wrong district, they could be voting for a commissioner who won't represent their neighborhood. Or they could be excluded from a race that directly affects them. Either way, it's a problem of **representation**.

In local elections, margins are often thin. Over a thousand voters assigned to the wrong district is not a rounding error.

I emailed my initial findings to county officials on February 4th -- Mr. Gillon and Ms. Evans -- along with the interactive map, the source data, and the code. I was transparent about the tension I felt:

> "Normally, I would prefer to do some double checking, verification, and separate analysis before bringing this to your attention. However, I think the upcoming special election calls for urgency."

I'd rather share early and be corrected than wait until after the election.

## Everything Is Open

Every part of this analysis is public and verifiable:

- **The source code** is on [GitHub](https://github.com/kerryhatcher/vote-match)
- **The voter roll data** comes from the Georgia Secretary of State -- publicly available
- **The district boundary maps** come from Macon-Bibb County's GIS system -- publicly available
- **The methodology** is documented in the repository

I don't want you to take my word for it. I want you to be able to check. As I told county officials: "I'm more than happy to share my source data and work, as well as collaborate with MBC GIS (or anyone) to independently verify the data."

Vote Match isn't limited to county commission districts, either. It supports all 17 district types found in Georgia voter registration data -- congressional, state senate, state house, school board, judicial, Public Service Commission, and more. And it's not limited to Macon-Bibb. Any county in Georgia with public voter rolls and GIS boundary data could run the same analysis.

## What You Can Do

**Check your own registration.** Visit the [Georgia My Voter Page](https://mvp.sos.ga.gov/) and verify your district assignments match where you actually live.

**If you live in Macon-Bibb County** -- especially in or near District 5 -- take a close look. Make sure you're registered in the right district before March 17th.

**Contact your officials.** If accurate voter-district assignments matter to you, let your commissioner and the Macon-Bibb Board of Elections know. Ask them to conduct an independent, professional audit of voter-district assignments before March 17th.

**Share this post.** The more people who check their registration, the better.

**If you're a developer or data person**, the tool is open source. Fork it, run it for your county, improve it, and let me know what you find.

---

This tool was built in 4 days by one person using public data and open-source software. That's the point. We don't have to wait for someone else to verify our own government's records. The data is there. The tools are there.

Let's make sure the data is right so that no one is disenfranchised.
