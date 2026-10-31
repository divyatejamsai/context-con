# Crustdata smoke report

Generated 2026-10-31 10:51:04 IST · stats `{'live': 7, 'cache': 8, 'fixture': 0, 'miss': 0, 'retries': 0, 'errors': 0}`

| step | status | rows | origin | secs |
|---|---|---|---|---|
| person_search | OK | 10 | cache | 0.0 |
| person_search_simple | OK | 5 | live | 1.8 |
| person_enrich | OK | 5 | cache | 0.0 |
| company_enrich_13599234 | OK | 1 | live | 0.8 |
| company_enrich_917316 | OK | 1 | live | 0.4 |
| company_enrich_6533485 | OK | 1 | live | 0.4 |
| company_enrich_1090701 | OK | 1 | live | 0.6 |
| company_enrich_4433230 | OK | 1 | live | 0.5 |
| company_enrich_631307 | OK | 1 | live | 0.6 |
| company_identify | OK | 1 | cache | 0.0 |
| company_enrich | OK | 1 | cache | 0.0 |
| company_search | OK | 5 | cache | 0.0 |
| job_search | OK | 5 | cache | 0.0 |
| web_search | OK | 9 | cache | 0.0 |
| web_fetch | OK | 1 | cache | 0.0 |

## person_search: fields of first record
```
crustdata_person_id  e.g. 314613
basic_profile.current_title  e.g. "Backend Engineer"
basic_profile.headline  e.g. "Building Tech at Fam | Ex-entrepreneur | IIT Roorkee"
basic_profile.location.city  e.g. "Bengaluru"
basic_profile.location.continent  e.g. "Asia"
basic_profile.location.country  e.g. "India"
basic_profile.location.full_location  e.g. "Bengaluru, Karnataka, India"
basic_profile.location.raw  e.g. "Bengaluru, Karnataka, India"
basic_profile.location.state  e.g. "Karnataka"
basic_profile.name  e.g. "Vinod Sonagara"
basic_profile.professional_network_name  e.g. "Vinod Sonagara"
basic_profile.profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/person/0
basic_profile.normalized_title  e.g. null
experience.employment_details.current[].business_email_verified  e.g. false
experience.employment_details.current[].company_headcount_latest  e.g. 1503
experience.employment_details.current[].company_headcount_range  e.g. "51-200"
experience.employment_details.current[].company_headquarters_country  e.g. "India"
experience.employment_details.current[].company_hq_location  e.g. "HSR Layout, Karnataka, India"
experience.employment_details.current[].company_hq_location_address_components[]  e.g. []
experience.employment_details.current[].company_industries[]  e.g. ["Financial Services"]
experience.employment_details.current[].company_professional_network_industry  e.g. "Financial Services"
experience.employment_details.current[].company_professional_network_profile_url  e.g. "https://www.linkedin.com/company/famappbytrio"
experience.employment_details.current[].company_profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
experience.employment_details.current[].company_status  e.g. "active"
experience.employment_details.current[].company_type  e.g. "Privately Held"
experience.employment_details.current[].company_website  e.g. "http://famapp.in"
experience.employment_details.current[].crustdata_company_id  e.g. 13599234
experience.employment_details.current[].description  e.g. ""
experience.employment_details.current[].employment_type  e.g. ""
experience.employment_details.current[].end_date  e.g. null
experience.employment_details.current[].function_category  e.g. "Engineering"
experience.employment_details.current[].is_default  e.g. true
experience.employment_details.current[].name  e.g. "Fam"
experience.employment_details.current[].position_id  e.g. 2704414624
experience.employment_details.current[].professional_network_id  e.g. "14618763"
experience.employment_details.current[].seniority_level  e.g. "Entry Level"
experience.employment_details.current[].start_date  e.g. "2025-05-01T00:00:00"
experience.employment_details.current[].title  e.g. "Backend Engineer"
experience.employment_details.current[].years_at_company  e.g. "1 to 2 years"
experience.employment_details.current[].years_at_company_raw  e.g. 1
experience.employment_details.past[].business_email_verified  e.g. false
experience.employment_details.past[].company_headcount_latest  e.g. 21
experience.employment_details.past[].company_headcount_range  e.g. "51-200"
experience.employment_details.past[].company_headquarters_country  e.g. "India"
experience.employment_details.past[].company_hq_location  e.g. "St. John's Medical College, Koramangala I Block, Koramangal
experience.employment_details.past[].company_hq_location_address_components[]  e.g. []
experience.employment_details.past[].company_industries[]  e.g. ["Technology, Information and Internet", "Technology, Inform
experience.employment_details.past[].company_professional_network_industry  e.g. "Technology, Information and Internet"
experience.employment_details.past[].company_professional_network_profile_url  e.g. "https://www.linkedin.com/company/newtral-io"
experience.employment_details.past[].company_profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
experience.employment_details.past[].company_status  e.g. "active"
experience.employment_details.past[].company_type  e.g. "Privately Held"
experience.employment_details.past[].company_website  e.g. "https://newtral.ai/"
experience.employment_details.past[].crustdata_company_id  e.g. 917316
experience.employment_details.past[].description  e.g. ""
experience.employment_details.past[].employment_type  e.g. ""
experience.employment_details.past[].end_date  e.g. "2025-03-01T00:00:00"
experience.employment_details.past[].function_category  e.g. ""
experience.employment_details.past[].is_default  e.g. false
experience.employment_details.past[].name  e.g. "Newtral"
experience.employment_details.past[].position_id  e.g. 2093307359
experience.employment_details.past[].professional_network_id  e.g. "82832151"
experience.employment_details.past[].seniority_level  e.g. "Owner / Partner"
experience.employment_details.past[].start_date  e.g. "2023-01-01T00:00:00"
experience.employment_details.past[].title  e.g. "Co-Founder"
experience.employment_details.past[].years_at_company  e.g. "3 to 5 years"
experience.employment_details.past[].years_at_company_raw  e.g. 2
experience.recently_changed_jobs  e.g. false
social_handles.dev_platform_identifier.profile_url  e.g. null
social_handles.professional_network_identifier.profile_url  e.g. "https://www.linkedin.com/in/vinod-sonagara"
social_handles.twitter_identifier.slug  e.g. ""
```

## person_search_simple: fields of first record
```
crustdata_person_id  e.g. 314613
basic_profile.current_title  e.g. "Backend Engineer"
basic_profile.headline  e.g. "Building Tech at Fam | Ex-entrepreneur | IIT Roorkee"
basic_profile.location.city  e.g. "Bengaluru"
basic_profile.location.continent  e.g. "Asia"
basic_profile.location.country  e.g. "India"
basic_profile.location.full_location  e.g. "Bengaluru, Karnataka, India"
basic_profile.location.raw  e.g. "Bengaluru, Karnataka, India"
basic_profile.location.state  e.g. "Karnataka"
basic_profile.name  e.g. "Vinod Sonagara"
basic_profile.professional_network_name  e.g. "Vinod Sonagara"
basic_profile.profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/person/0
basic_profile.normalized_title  e.g. null
experience.employment_details.current[].business_email_verified  e.g. false
experience.employment_details.current[].company_headcount_latest  e.g. 1503
experience.employment_details.current[].company_headcount_range  e.g. "51-200"
experience.employment_details.current[].company_headquarters_country  e.g. "India"
experience.employment_details.current[].company_hq_location  e.g. "HSR Layout, Karnataka, India"
experience.employment_details.current[].company_hq_location_address_components[]  e.g. []
experience.employment_details.current[].company_industries[]  e.g. ["Financial Services"]
experience.employment_details.current[].company_professional_network_industry  e.g. "Financial Services"
experience.employment_details.current[].company_professional_network_profile_url  e.g. "https://www.linkedin.com/company/famappbytrio"
experience.employment_details.current[].company_profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
experience.employment_details.current[].company_status  e.g. "active"
experience.employment_details.current[].company_type  e.g. "Privately Held"
experience.employment_details.current[].company_website  e.g. "http://famapp.in"
experience.employment_details.current[].crustdata_company_id  e.g. 13599234
experience.employment_details.current[].description  e.g. ""
experience.employment_details.current[].employment_type  e.g. ""
experience.employment_details.current[].end_date  e.g. null
experience.employment_details.current[].function_category  e.g. "Engineering"
experience.employment_details.current[].is_default  e.g. true
experience.employment_details.current[].name  e.g. "Fam"
experience.employment_details.current[].position_id  e.g. 2704414624
experience.employment_details.current[].professional_network_id  e.g. "14618763"
experience.employment_details.current[].seniority_level  e.g. "Entry Level"
experience.employment_details.current[].start_date  e.g. "2025-05-01T00:00:00"
experience.employment_details.current[].title  e.g. "Backend Engineer"
experience.employment_details.current[].years_at_company  e.g. "1 to 2 years"
experience.employment_details.current[].years_at_company_raw  e.g. 1
experience.employment_details.past[].business_email_verified  e.g. false
experience.employment_details.past[].company_headcount_latest  e.g. 21
experience.employment_details.past[].company_headcount_range  e.g. "51-200"
experience.employment_details.past[].company_headquarters_country  e.g. "India"
experience.employment_details.past[].company_hq_location  e.g. "St. John's Medical College, Koramangala I Block, Koramangal
experience.employment_details.past[].company_hq_location_address_components[]  e.g. []
experience.employment_details.past[].company_industries[]  e.g. ["Technology, Information and Internet", "Technology, Inform
experience.employment_details.past[].company_professional_network_industry  e.g. "Technology, Information and Internet"
experience.employment_details.past[].company_professional_network_profile_url  e.g. "https://www.linkedin.com/company/newtral-io"
experience.employment_details.past[].company_profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
experience.employment_details.past[].company_status  e.g. "active"
experience.employment_details.past[].company_type  e.g. "Privately Held"
experience.employment_details.past[].company_website  e.g. "https://newtral.ai/"
experience.employment_details.past[].crustdata_company_id  e.g. 917316
experience.employment_details.past[].description  e.g. ""
experience.employment_details.past[].employment_type  e.g. ""
experience.employment_details.past[].end_date  e.g. "2025-03-01T00:00:00"
experience.employment_details.past[].function_category  e.g. ""
experience.employment_details.past[].is_default  e.g. false
experience.employment_details.past[].name  e.g. "Newtral"
experience.employment_details.past[].position_id  e.g. 2093307359
experience.employment_details.past[].professional_network_id  e.g. "82832151"
experience.employment_details.past[].seniority_level  e.g. "Owner / Partner"
experience.employment_details.past[].start_date  e.g. "2023-01-01T00:00:00"
experience.employment_details.past[].title  e.g. "Co-Founder"
experience.employment_details.past[].years_at_company  e.g. "3 to 5 years"
experience.employment_details.past[].years_at_company_raw  e.g. 2
experience.recently_changed_jobs  e.g. false
social_handles.dev_platform_identifier.profile_url  e.g. null
social_handles.professional_network_identifier.profile_url  e.g. "https://www.linkedin.com/in/vinod-sonagara"
social_handles.twitter_identifier.slug  e.g. ""
```

## person_enrich: fields of first record
```
basic_profile.current_title  e.g. "Backend Engineer"
basic_profile.first_name  e.g. "Vinod"
basic_profile.headline  e.g. "Building Tech at Fam | Ex-entrepreneur | IIT Roorkee"
basic_profile.languages[]  e.g. ["English (Full professional proficiency)", "Hindi (Native o
basic_profile.last_name  e.g. "Sonagara"
basic_profile.location.city  e.g. "Bengaluru"
basic_profile.location.continent  e.g. "Asia"
basic_profile.location.country  e.g. "India"
basic_profile.location.full_location  e.g. null
basic_profile.location.raw  e.g. "Bengaluru, Karnataka, India"
basic_profile.location.state  e.g. "Karnataka"
basic_profile.name  e.g. "Vinod Sonagara"
basic_profile.professional_network_name  e.g. "Vinod Sonagara"
basic_profile.profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/person/0
basic_profile.summary  e.g. "At Newtral, I lead the development of an AI-powered sustain
education.schools[].activities_and_societies  e.g. ""
education.schools[].degree  e.g. "Bachelor of Technology (B.Tech.)"
education.schools[].description  e.g. ""
education.schools[].end_year  e.g. 2019
education.schools[].field_of_study  e.g. "Electrical Engineering Technologies/Technicians"
education.schools[].institute_logo_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
education.schools[].institute_logo_url  e.g. "https://media.licdn.com/dms/image/v2/C510BAQFxnsvax1W4UQ/co
education.schools[].location.city  e.g. "Roorkee"
education.schools[].location.continent  e.g. "Asia"
education.schools[].location.country  e.g. "India"
education.schools[].location.raw  e.g. "Roorkee, Uttarakhand"
education.schools[].location.state  e.g. "Uttarakhand"
education.schools[].professional_network_id  e.g. "157269"
education.schools[].school  e.g. "Indian Institute of Technology, Roorkee"
education.schools[].start_year  e.g. 2014
experience.employment_details.current[].company_description  e.g. "Fam, formerly FamPay, focuses on financial inclusion of the
experience.employment_details.current[].company_headcount_latest  e.g. 1503
experience.employment_details.current[].company_headcount_range  e.g. "51-200"
experience.employment_details.current[].company_industries[]  e.g. ["Financial Services"]
experience.employment_details.current[].company_professional_network_industry  e.g. "Financial Services"
experience.employment_details.current[].company_professional_network_profile_url  e.g. "https://linkedin.com/company/14618763"
experience.employment_details.current[].company_profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
experience.employment_details.current[].company_status  e.g. "active"
experience.employment_details.current[].company_website  e.g. "http://famapp.in"
experience.employment_details.current[].company_website_domain  e.g. "famapp.in"
experience.employment_details.current[].crustdata_company_id  e.g. 13599234
experience.employment_details.current[].description  e.g. ""
experience.employment_details.current[].employment_type  e.g. ""
experience.employment_details.current[].end_date  e.g. null
experience.employment_details.current[].function_category  e.g. "Engineering"
experience.employment_details.current[].is_default  e.g. true
experience.employment_details.current[].name  e.g. "Fam"
experience.employment_details.current[].position_id  e.g. 2704414624
experience.employment_details.current[].professional_network_id  e.g. "14618763"
experience.employment_details.current[].seniority_level  e.g. "Entry Level"
experience.employment_details.current[].start_date  e.g. "2025-05-01T00:00:00+00:00"
experience.employment_details.current[].title  e.g. "Backend Engineer"
experience.employment_details.current[].years_at_company  e.g. "1 to 2 years"
experience.employment_details.current[].years_at_company_raw  e.g. 1.0
experience.employment_details.past[].company_description  e.g. "Newtral is an AI company for compliance and sustainability 
experience.employment_details.past[].company_headcount_latest  e.g. 21
experience.employment_details.past[].company_headcount_range  e.g. "51-200"
experience.employment_details.past[].company_industries[]  e.g. ["Technology, Information and Internet", "Technology, Inform
experience.employment_details.past[].company_professional_network_industry  e.g. "Technology, Information and Internet"
experience.employment_details.past[].company_professional_network_profile_url  e.g. "https://linkedin.com/company/82832151"
experience.employment_details.past[].company_profile_picture_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
experience.employment_details.past[].company_status  e.g. "active"
experience.employment_details.past[].company_website  e.g. "https://newtral.ai/"
experience.employment_details.past[].company_website_domain  e.g. "newtral.io"
experience.employment_details.past[].crustdata_company_id  e.g. 917316
experience.employment_details.past[].description  e.g. ""
experience.employment_details.past[].employment_type  e.g. ""
experience.employment_details.past[].end_date  e.g. "2025-03-01T00:00:00+00:00"
experience.employment_details.past[].function_category  e.g. ""
experience.employment_details.past[].is_default  e.g. false
experience.employment_details.past[].name  e.g. "Newtral"
experience.employment_details.past[].position_id  e.g. 2093307359
experience.employment_details.past[].professional_network_id  e.g. "82832151"
experience.employment_details.past[].seniority_level  e.g. "Owner / Partner"
experience.employment_details.past[].start_date  e.g. "2023-01-01T00:00:00+00:00"
experience.employment_details.past[].title  e.g. "Co-Founder"
experience.employment_details.past[].years_at_company  e.g. "3 to 5 years"
experience.employment_details.past[].years_at_company_raw  e.g. 2.0
skills.professional_network_skills[]  e.g. ["Software Development", "Artificial Intelligence (AI)"]
social_handles.dev_platform_identifier.profile_url  e.g. null
social_handles.professional_network_identifier.profile_url  e.g. "https://www.linkedin.com/in/vinod-sonagara"
social_handles.twitter_identifier.slug  e.g. ""
crustdata_person_id  e.g. 314613
_match.confidence_score  e.g. 1.0
_match.match_type  e.g. "professional_network_profile_url"
_match.match_status  e.g. "matched"
```

## company_enrich_13599234: fields of first record
```
crustdata_company_id  e.g. 13599234
funding.contact_email  e.g. null
funding.is_investor  e.g. false
funding.phone_number  e.g. null
funding.funds_total_usd  e.g. null
funding.last_fund_date  e.g. null
funding.num_funding_rounds  e.g. null
funding.num_funds  e.g. null
funding.total_investment_usd  e.g. null
funding.last_round_amount_usd  e.g. null
funding.last_round_type  e.g. null
funding.investors  e.g. null
funding.last_fundraise_date  e.g. null
headcount.largest_headcount_country  e.g. "IND"
headcount.total  e.g. 1503
headcount.growth_percent.mom  e.g. 1.7603249830737984
headcount.growth_percent.qoq  e.g. 3.512396694214876
headcount.growth_percent.six_months  e.g. 6.294200848656294
headcount.growth_percent.yoy  e.g. 19.475357710651828
headcount.growth_percent.two_years  e.g. 43.69024856596558
headcount.growth_absolute.mom  e.g. 26
headcount.growth_absolute.qoq  e.g. 51
headcount.growth_absolute.six_months  e.g. 89
headcount.growth_absolute.yoy  e.g. 245
headcount.growth_absolute.two_years  e.g. 457
headcount.by_role_absolute.Entrepreneurship  e.g. 23
headcount.by_role_absolute.Support  e.g. 30
headcount.by_role_absolute.Healthcare Services  e.g. 58
headcount.by_role_absolute.Arts and Design  e.g. 66
headcount.by_role_absolute.Education  e.g. 112
headcount.by_role_absolute.Operations  e.g. 216
headcount.by_role_absolute.Community and Social Services  e.g. 42
headcount.by_role_absolute.Finance  e.g. 23
headcount.by_role_absolute.Information Technology  e.g. 25
headcount.by_role_absolute.Media and Communication  e.g. 30
headcount.by_role_absolute.Sales  e.g. 71
headcount.by_role_absolute.Accounting  e.g. 24
headcount.by_role_absolute.Engineering  e.g. 137
headcount.by_role_absolute.Business Development  e.g. 96
headcount.by_role_absolute.Administrative  e.g. 51
headcount.by_role_percent.Entrepreneurship  e.g. 1.5302727877578177
headcount.by_role_percent.Support  e.g. 1.996007984031936
headcount.by_role_percent.Healthcare Services  e.g. 3.8589487691284097
headcount.by_role_percent.Arts and Design  e.g. 4.39121756487026
headcount.by_role_percent.Education  e.g. 7.451763140385895
headcount.by_role_percent.Operations  e.g. 14.37125748502994
headcount.by_role_percent.Community and Social Services  e.g. 2.7944111776447107
headcount.by_role_percent.Finance  e.g. 1.5302727877578177
headcount.by_role_percent.Information Technology  e.g. 1.66333998669328
headcount.by_role_percent.Media and Communication  e.g. 1.996007984031936
headcount.by_role_percent.Sales  e.g. 4.723885562208915
headcount.by_role_percent.Accounting  e.g. 1.5968063872255487
headcount.by_role_percent.Engineering  e.g. 9.115103127079175
headcount.by_role_percent.Business Development  e.g. 6.387225548902195
headcount.by_role_percent.Administrative  e.g. 3.3932135728542914
headcount.by_role_growth_6m_pct.Administrative  e.g. 4.081632653061225
headcount.by_role_growth_6m_pct.Marketing  e.g. 10.526315789473683
headcount.by_role_growth_6m_pct.Support  e.g. 7.142857142857142
headcount.by_role_growth_6m_pct.Education  e.g. 5.660377358490567
headcount.by_role_growth_6m_pct.Sales  e.g. 12.698412698412698
headcount.by_role_growth_6m_pct.Arts and Design  e.g. 3.125
headcount.by_role_growth_6m_pct.Program and Project Management  e.g. -9.090909090909092
headcount.by_role_growth_6m_pct.Real Estate  e.g. 50.0
headcount.by_role_growth_6m_pct.Engineering  e.g. 14.166666666666666
headcount.by_role_growth_6m_pct.Legal  e.g. 7.142857142857142
headcount.by_role_growth_6m_pct.Quality Assurance  e.g. 25.0
headcount.by_role_growth_6m_pct.Information Technology  e.g. 4.166666666666666
headcount.by_role_growth_6m_pct.Human Resources  e.g. -5.263157894736842
headcount.by_role_growth_6m_pct.Consulting  e.g. 0.0
headcount.by_role_growth_6m_pct.Entrepreneurship  e.g. 21.052631578947366
headcount.by_role_growth_6m_pct.Healthcare Services  e.g. 11.538461538461538
headcount.by_role_growth_6m_pct.Finance  e.g. 4.545454545454546
headcount.by_role_growth_6m_pct.Accounting  e.g. 9.090909090909092
headcount.by_role_growth_6m_pct.Customer Success and Support  e.g. 7.142857142857142
headcount.by_role_growth_6m_pct.Military and Protective Services  e.g. 0.0
headcount.by_role_growth_6m_pct.Product Management  e.g. 100.0
headcount.by_role_growth_6m_pct.Business Development  e.g. 7.865168539325842
headcount.by_role_growth_6m_pct.Media and Communication  e.g. 15.384615384615385
headcount.by_role_growth_6m_pct.Operations  e.g. 10.204081632653061
headcount.by_role_growth_6m_pct.Purchasing  e.g. 0.0
headcount.by_role_growth_6m_pct.Research  e.g. 7.6923076923076925
headcount.by_role_growth_6m_pct.Community and Social Services  e.g. 13.513513513513514
headcount.by_role_growth_yoy_pct.Administrative  e.g. 4.081632653061225
headcount.by_role_growth_yoy_pct.Marketing  e.g. 23.52941176470588
headcount.by_role_growth_yoy_pct.Education  e.g. 14.285714285714285
headcount.by_role_growth_yoy_pct.Sales  e.g. 16.39344262295082
headcount.by_role_growth_yoy_pct.Arts and Design  e.g. 15.789473684210526
headcount.by_role_growth_yoy_pct.Program and Project Management  e.g. 11.11111111111111
headcount.by_role_growth_yoy_pct.Real Estate  e.g. 0.0
headcount.by_role_growth_yoy_pct.Engineering  e.g. 39.795918367346935
headcount.by_role_growth_yoy_pct.Legal  e.g. 25.0
headcount.by_role_growth_yoy_pct.Quality Assurance  e.g. 0.0
headcount.by_role_growth_yoy_pct.Information Technology  e.g. 19.047619047619047
headcount.by_role_growth_yoy_pct.Human Resources  e.g. -5.263157894736842
headcount.by_role_growth_yoy_pct.Consulting  e.g. 0.0
headcount.by_role_growth_yoy_pct.Entrepreneurship  e.g. 21.052631578947366
headcount.by_role_growth_yoy_pct.Healthcare Services  e.g. 13.725490196078432
headcount.by_role_growth_yoy_pct.Finance  e.g. 4.545454545454546
headcount.by_role_growth_yoy_pct.Accounting  e.g. 20.0
headcount.by_role_growth_yoy_pct.Customer Success and Support  e.g. 20.0
headcount.by_role_growth_yoy_pct.Military and Protective Services  e.g. 20.0
headcount.by_role_growth_yoy_pct.Product Management  e.g. 300.0
headcount.by_role_growth_yoy_pct.Business Development  e.g. 17.073170731707318
headcount.by_role_growth_yoy_pct.Media and Communication  e.g. 20.0
headcount.by_role_growth_yoy_pct.Operations  e.g. 26.31578947368421
headcount.by_role_growth_yoy_pct.Purchasing  e.g. 0.0
headcount.by_role_growth_yoy_pct.Research  e.g. 27.27272727272727
headcount.by_role_growth_yoy_pct.Community and Social Services  e.g. 23.52941176470588
headcount.by_region_absolute.Chile  e.g. 53
headcount.by_region_absolute.Brazil  e.g. 114
headcount.by_region_absolute.Mexico City Metropolitan Area  e.g. 28
headcount.by_region_absolute.Mexico  e.g. 109
headcount.by_region_absolute.Greater São Paulo Area  e.g. 29
headcount.by_region_absolute.Karnataka, India  e.g. 146
headcount.by_region_absolute.Mumbai Metropolitan Region  e.g. 25
headcount.by_region_absolute.Bengaluru  e.g. 140
headcount.by_region_absolute.Maharashtra, India  e.g. 53
headcount.by_region_absolute.Uttar Pradesh, India  e.g. 37
headcount.by_region_absolute.Greater Bengaluru Area  e.g. 142
headcount.by_region_absolute.São Paulo, Brazil  e.g. 59
```

## company_enrich_917316: fields of first record
```
crustdata_company_id  e.g. 917316
funding.acquired_by[]  e.g. []
funding.acquisitions[]  e.g. []
funding.investors_detailed[].crunchbase_profile_url  e.g. "https://www.crunchbase.com/organization/angelbay-holdings"
funding.investors_detailed[].permalink  e.g. "angelbay-holdings"
funding.investors_detailed[].name  e.g. "Angelbay"
funding.investors_detailed[].uuid  e.g. "c4a3fdcc-22c6-4ba5-b888-82abadf91015"
funding.investors_detailed[].type  e.g. "organization"
funding.investors_detailed[].categories[]  e.g. ["angel_group"]
funding.milestones[].round_type  e.g. "seed"
funding.milestones[].is_fund  e.g. false
funding.milestones[].permalink  e.g. "newtral-io-seed--b887dd6f"
funding.milestones[].date  e.g. "2025-08-27"
funding.milestones[].funding_date  e.g. "2025-08-27"
funding.milestones[].amount_usd  e.g. 600000.0
funding.milestones[].investors  e.g. "NOW Venture Studio"
funding.milestones[].lead_investors  e.g. null
funding.contact_email  e.g. "avi@newtral.io"
funding.is_investor  e.g. false
funding.phone_number  e.g. "+91-9033408242"
funding.funds_total_usd  e.g. null
funding.last_fund_date  e.g. null
funding.num_funding_rounds  e.g. 3
funding.num_funds  e.g. 0
funding.total_investment_usd  e.g. 678072.0
funding.last_round_amount_usd  e.g. 600000.0
funding.last_round_type  e.g. "seed"
funding.investors[]  e.g. ["Angelbay", "NOW Venture Studio"]
funding.last_fundraise_date  e.g. "2025-08-27"
headcount.largest_headcount_country  e.g. "IND"
headcount.total  e.g. 21
headcount.growth_percent.mom  e.g. 0.0
headcount.growth_percent.qoq  e.g. -4.545454545454546
headcount.growth_percent.six_months  e.g. -4.545454545454546
headcount.growth_percent.yoy  e.g. 10.526315789473683
headcount.growth_percent.two_years  e.g. 75.0
headcount.growth_absolute.mom  e.g. 0
headcount.growth_absolute.qoq  e.g. -1
headcount.growth_absolute.six_months  e.g. -1
headcount.growth_absolute.yoy  e.g. 2
headcount.growth_absolute.two_years  e.g. 9
headcount.by_role_absolute.Sales  e.g. 2
headcount.by_role_absolute.Engineering  e.g. 5
headcount.by_role_absolute.Marketing  e.g. 1
headcount.by_role_absolute.Community and Social Services  e.g. 1
headcount.by_role_absolute.Arts and Design  e.g. 1
headcount.by_role_absolute.Consulting  e.g. 1
headcount.by_role_absolute.Information Technology  e.g. 4
headcount.by_role_absolute.Support  e.g. 1
headcount.by_role_absolute.Business Development  e.g. 4
headcount.by_role_percent.Sales  e.g. 9.523809523809524
headcount.by_role_percent.Engineering  e.g. 23.809523809523807
headcount.by_role_percent.Marketing  e.g. 4.761904761904762
headcount.by_role_percent.Community and Social Services  e.g. 4.761904761904762
headcount.by_role_percent.Arts and Design  e.g. 4.761904761904762
headcount.by_role_percent.Consulting  e.g. 4.761904761904762
headcount.by_role_percent.Information Technology  e.g. 19.047619047619047
headcount.by_role_percent.Support  e.g. 4.761904761904762
headcount.by_role_percent.Business Development  e.g. 19.047619047619047
headcount.by_role_growth_6m_pct.Sales  e.g. 0.0
headcount.by_role_growth_6m_pct.Arts and Design  e.g. 0.0
headcount.by_role_growth_6m_pct.Business Development  e.g. 0.0
headcount.by_role_growth_6m_pct.Engineering  e.g. -16.666666666666664
headcount.by_role_growth_6m_pct.Support  e.g. 0.0
headcount.by_role_growth_6m_pct.Information Technology  e.g. 100.0
headcount.by_role_growth_6m_pct.Community and Social Services  e.g. 0.0
headcount.by_role_growth_6m_pct.Customer Success and Support  e.g. 0.0
headcount.by_role_growth_yoy_pct.Sales  e.g. -50.0
headcount.by_role_growth_yoy_pct.Arts and Design  e.g. 0.0
headcount.by_role_growth_yoy_pct.Business Development  e.g. 33.33333333333333
headcount.by_role_growth_yoy_pct.Engineering  e.g. 0.0
headcount.by_role_growth_yoy_pct.Information Technology  e.g. 100.0
headcount.by_role_growth_yoy_pct.Customer Success and Support  e.g. 0.0
headcount.by_region_absolute.Karnataka, India  e.g. 14
headcount.by_region_absolute.Maharashtra, India  e.g. 3
headcount.by_region_absolute.Dharampur  e.g. 1
headcount.by_region_absolute.Bengaluru  e.g. 13
headcount.by_region_absolute.India  e.g. 21
headcount.by_region_absolute.Haryana, India  e.g. 1
headcount.by_region_absolute.Pune Division  e.g. 2
headcount.by_region_absolute.Delhi, India  e.g. 1
headcount.by_region_absolute.Greater Bengaluru Area  e.g. 14
headcount.by_region_absolute.Gurugram  e.g. 1
headcount.by_region_absolute.Pune/Pimpri-Chinchwad Area  e.g. 2
headcount.by_region_absolute.Greater Delhi Area  e.g. 2
headcount.by_region_absolute.Bhavnagar  e.g. 1
headcount.by_region_absolute.Gujarat, India  e.g. 2
headcount.by_region_absolute.Mumbai  e.g. 1
headcount.by_region_percent.Karnataka, India  e.g. 66.66666666666666
headcount.by_region_percent.Maharashtra, India  e.g. 14.285714285714285
headcount.by_region_percent.Dharampur  e.g. 4.761904761904762
headcount.by_region_percent.Bengaluru  e.g. 61.904761904761905
headcount.by_region_percent.India  e.g. 100.0
headcount.by_region_percent.Haryana, India  e.g. 4.761904761904762
headcount.by_region_percent.Pune Division  e.g. 9.523809523809524
headcount.by_region_percent.Delhi, India  e.g. 4.761904761904762
headcount.by_region_percent.Greater Bengaluru Area  e.g. 66.66666666666666
headcount.by_region_percent.Gurugram  e.g. 4.761904761904762
headcount.by_region_percent.Pune/Pimpri-Chinchwad Area  e.g. 9.523809523809524
headcount.by_region_percent.Greater Delhi Area  e.g. 9.523809523809524
headcount.by_region_percent.Bhavnagar  e.g. 4.761904761904762
headcount.by_region_percent.Gujarat, India  e.g. 9.523809523809524
headcount.by_region_percent.Mumbai  e.g. 4.761904761904762
headcount.by_skill_absolute.Software as a Service (SaaS)  e.g. 3
headcount.by_skill_absolute.Sales Development  e.g. 2
headcount.by_skill_absolute.Teamwork  e.g. 4
headcount.by_skill_absolute.Data Analysis  e.g. 3
headcount.by_skill_absolute.Public Speaking  e.g. 6
headcount.by_skill_absolute.TypeScript  e.g. 4
headcount.by_skill_absolute.Adobe Illustrator  e.g. 3
headcount.by_skill_absolute.Leadership  e.g. 8
headcount.by_skill_absolute.Team Management  e.g. 7
headcount.by_skill_absolute.GitHub  e.g. 3
headcount.by_skill_absolute.React.js  e.g. 4
headcount.by_skill_absolute.Communication  e.g. 6
headcount.by_skill_absolute.Business Development  e.g. 6
headcount.by_skill_absolute.Express.js  e.g. 3
headcount.by_skill_absolute.Python (Programming Language)  e.g. 4
headcount.by_skill_absolute.Environmental, Social, and Governance (ESG)  e.g. 4
headcount.by_skill_absolute.MongoDB  e.g. 5
```

## company_enrich_6533485: fields of first record
```
crustdata_company_id  e.g. 6533485
funding.acquired_by[]  e.g. []
funding.acquisitions[]  e.g. []
funding.contact_email  e.g. "support@kiot.io"
funding.is_investor  e.g. false
funding.phone_number  e.g. "+91 99499 98052"
funding.funds_total_usd  e.g. null
funding.last_fund_date  e.g. null
funding.num_funding_rounds  e.g. 0
funding.num_funds  e.g. 0
funding.total_investment_usd  e.g. 0.0
funding.last_round_amount_usd  e.g. null
funding.last_round_type  e.g. null
funding.investors  e.g. null
funding.last_fundraise_date  e.g. null
headcount.largest_headcount_country  e.g. "IND"
headcount.total  e.g. 108
headcount.growth_percent.mom  e.g. 0.0
headcount.growth_percent.qoq  e.g. 1.8867924528301887
headcount.growth_percent.six_months  e.g. 2.857142857142857
headcount.growth_percent.yoy  e.g. 6.9306930693069315
headcount.growth_percent.two_years  e.g. 28.57142857142857
headcount.growth_absolute.mom  e.g. 0
headcount.growth_absolute.qoq  e.g. 2
headcount.growth_absolute.six_months  e.g. 3
headcount.growth_absolute.yoy  e.g. 7
headcount.growth_absolute.two_years  e.g. 24
headcount.by_role_absolute.Engineering  e.g. 25
headcount.by_role_absolute.Purchasing  e.g. 2
headcount.by_role_absolute.Accounting  e.g. 2
headcount.by_role_absolute.Research  e.g. 4
headcount.by_role_absolute.Business Development  e.g. 18
headcount.by_role_absolute.Healthcare Services  e.g. 5
headcount.by_role_absolute.Quality Assurance  e.g. 2
headcount.by_role_absolute.Sales  e.g. 11
headcount.by_role_absolute.Human Resources  e.g. 5
headcount.by_role_absolute.Education  e.g. 8
headcount.by_role_absolute.Information Technology  e.g. 4
headcount.by_role_absolute.Marketing  e.g. 2
headcount.by_role_absolute.Operations  e.g. 16
headcount.by_role_percent.Engineering  e.g. 23.14814814814815
headcount.by_role_percent.Purchasing  e.g. 1.8518518518518516
headcount.by_role_percent.Accounting  e.g. 1.8518518518518516
headcount.by_role_percent.Research  e.g. 3.7037037037037033
headcount.by_role_percent.Business Development  e.g. 16.666666666666664
headcount.by_role_percent.Healthcare Services  e.g. 4.62962962962963
headcount.by_role_percent.Quality Assurance  e.g. 1.8518518518518516
headcount.by_role_percent.Sales  e.g. 10.185185185185185
headcount.by_role_percent.Human Resources  e.g. 4.62962962962963
headcount.by_role_percent.Education  e.g. 7.4074074074074066
headcount.by_role_percent.Information Technology  e.g. 3.7037037037037033
headcount.by_role_percent.Marketing  e.g. 1.8518518518518516
headcount.by_role_percent.Operations  e.g. 14.814814814814813
headcount.by_role_growth_6m_pct.Accounting  e.g. 0.0
headcount.by_role_growth_6m_pct.Media and Communication  e.g. 0.0
headcount.by_role_growth_6m_pct.Customer Success and Support  e.g. 0.0
headcount.by_role_growth_6m_pct.Healthcare Services  e.g. 0.0
headcount.by_role_growth_6m_pct.Human Resources  e.g. 25.0
headcount.by_role_growth_6m_pct.Quality Assurance  e.g. 0.0
headcount.by_role_growth_6m_pct.Community and Social Services  e.g. 0.0
headcount.by_role_growth_6m_pct.Marketing  e.g. 0.0
headcount.by_role_growth_6m_pct.Sales  e.g. 10.0
headcount.by_role_growth_6m_pct.Information Technology  e.g. 33.33333333333333
headcount.by_role_growth_6m_pct.Research  e.g. 0.0
headcount.by_role_growth_6m_pct.Engineering  e.g. 0.0
headcount.by_role_growth_6m_pct.Business Development  e.g. 28.57142857142857
headcount.by_role_growth_6m_pct.Program and Project Management  e.g. 0.0
headcount.by_role_growth_6m_pct.Education  e.g. 0.0
headcount.by_role_growth_6m_pct.Operations  e.g. 6.666666666666667
headcount.by_role_growth_6m_pct.Administrative  e.g. 0.0
headcount.by_role_growth_6m_pct.Purchasing  e.g. 0.0
headcount.by_role_growth_yoy_pct.Accounting  e.g. 0.0
headcount.by_role_growth_yoy_pct.Media and Communication  e.g. 0.0
headcount.by_role_growth_yoy_pct.Customer Success and Support  e.g. 0.0
headcount.by_role_growth_yoy_pct.Healthcare Services  e.g. 0.0
headcount.by_role_growth_yoy_pct.Human Resources  e.g. 25.0
headcount.by_role_growth_yoy_pct.Quality Assurance  e.g. -33.33333333333333
headcount.by_role_growth_yoy_pct.Community and Social Services  e.g. 0.0
headcount.by_role_growth_yoy_pct.Marketing  e.g. 0.0
headcount.by_role_growth_yoy_pct.Sales  e.g. 37.5
headcount.by_role_growth_yoy_pct.Information Technology  e.g. 33.33333333333333
headcount.by_role_growth_yoy_pct.Research  e.g. 33.33333333333333
headcount.by_role_growth_yoy_pct.Engineering  e.g. 4.166666666666666
headcount.by_role_growth_yoy_pct.Business Development  e.g. 50.0
headcount.by_role_growth_yoy_pct.Program and Project Management  e.g. 0.0
headcount.by_role_growth_yoy_pct.Education  e.g. 0.0
headcount.by_role_growth_yoy_pct.Operations  e.g. 23.076923076923077
headcount.by_role_growth_yoy_pct.Administrative  e.g. 0.0
headcount.by_role_growth_yoy_pct.Purchasing  e.g. -33.33333333333333
headcount.by_region_absolute.Kanpur  e.g. 2
headcount.by_region_absolute.India  e.g. 104
headcount.by_region_absolute.Andhra Pradesh, India  e.g. 3
headcount.by_region_absolute.Kolhapur  e.g. 3
headcount.by_region_absolute.Greater Hyderabad Area  e.g. 75
headcount.by_region_absolute.Hyderabad  e.g. 71
headcount.by_region_absolute.Telangana, India  e.g. 75
headcount.by_region_absolute.Uttar Pradesh, India  e.g. 7
headcount.by_region_absolute.Ahmedabad  e.g. 2
headcount.by_region_absolute.Gujarat, India  e.g. 2
headcount.by_region_absolute.Maharashtra, India  e.g. 7
headcount.by_region_absolute.Salem  e.g. 2
headcount.by_region_absolute.Tamil Nadu, India  e.g. 5
headcount.by_region_absolute.Namakkal  e.g. 2
headcount.by_region_absolute.Vietnam  e.g. 2
headcount.by_region_percent.Kanpur  e.g. 1.8518518518518516
headcount.by_region_percent.India  e.g. 96.29629629629629
headcount.by_region_percent.Andhra Pradesh, India  e.g. 2.7777777777777777
headcount.by_region_percent.Kolhapur  e.g. 2.7777777777777777
headcount.by_region_percent.Greater Hyderabad Area  e.g. 69.44444444444444
headcount.by_region_percent.Hyderabad  e.g. 65.74074074074075
headcount.by_region_percent.Telangana, India  e.g. 69.44444444444444
headcount.by_region_percent.Uttar Pradesh, India  e.g. 6.481481481481481
headcount.by_region_percent.Ahmedabad  e.g. 1.8518518518518516
headcount.by_region_percent.Gujarat, India  e.g. 1.8518518518518516
headcount.by_region_percent.Maharashtra, India  e.g. 6.481481481481481
headcount.by_region_percent.Salem  e.g. 1.8518518518518516
headcount.by_region_percent.Tamil Nadu, India  e.g. 4.62962962962963
headcount.by_region_percent.Namakkal  e.g. 1.8518518518518516
headcount.by_region_percent.Vietnam  e.g. 1.8518518518518516
headcount.by_skill_absolute.Internet of Things (IoT)  e.g. 7
```

## company_enrich_1090701: fields of first record
```
crustdata_company_id  e.g. 1090701
funding.acquired_by[]  e.g. []
funding.acquisitions[]  e.g. []
funding.contact_email  e.g. "info@grewon.com"
funding.is_investor  e.g. false
funding.phone_number  e.g. "97121 30315"
funding.funds_total_usd  e.g. null
funding.last_fund_date  e.g. null
funding.num_funding_rounds  e.g. 0
funding.num_funds  e.g. 0
funding.total_investment_usd  e.g. 0.0
funding.last_round_amount_usd  e.g. null
funding.last_round_type  e.g. null
funding.investors  e.g. null
funding.last_fundraise_date  e.g. null
headcount.largest_headcount_country  e.g. "IND"
headcount.total  e.g. 59
headcount.growth_percent.mom  e.g. 0.0
headcount.growth_percent.qoq  e.g. 0.0
headcount.growth_percent.six_months  e.g. -4.838709677419355
headcount.growth_percent.yoy  e.g. -7.8125
headcount.growth_percent.two_years  e.g. 0.0
headcount.growth_absolute.mom  e.g. 0
headcount.growth_absolute.qoq  e.g. 0
headcount.growth_absolute.six_months  e.g. -3
headcount.growth_absolute.yoy  e.g. -5
headcount.growth_absolute.two_years  e.g. 0
headcount.by_role_absolute.Marketing  e.g. 1
headcount.by_role_absolute.Business Development  e.g. 3
headcount.by_role_absolute.Education  e.g. 2
headcount.by_role_absolute.Operations  e.g. 1
headcount.by_role_absolute.Community and Social Services  e.g. 1
headcount.by_role_absolute.Program and Project Management  e.g. 1
headcount.by_role_absolute.Arts and Design  e.g. 9
headcount.by_role_absolute.Human Resources  e.g. 1
headcount.by_role_absolute.Information Technology  e.g. 2
headcount.by_role_absolute.Quality Assurance  e.g. 3
headcount.by_role_absolute.Engineering  e.g. 35
headcount.by_role_percent.Marketing  e.g. 1.694915254237288
headcount.by_role_percent.Business Development  e.g. 5.084745762711865
headcount.by_role_percent.Education  e.g. 3.389830508474576
headcount.by_role_percent.Operations  e.g. 1.694915254237288
headcount.by_role_percent.Community and Social Services  e.g. 1.694915254237288
headcount.by_role_percent.Program and Project Management  e.g. 1.694915254237288
headcount.by_role_percent.Arts and Design  e.g. 15.254237288135593
headcount.by_role_percent.Human Resources  e.g. 1.694915254237288
headcount.by_role_percent.Information Technology  e.g. 3.389830508474576
headcount.by_role_percent.Quality Assurance  e.g. 5.084745762711865
headcount.by_role_percent.Engineering  e.g. 59.32203389830508
headcount.by_role_growth_6m_pct.Operations  e.g. 0.0
headcount.by_role_growth_6m_pct.Program and Project Management  e.g. 0.0
headcount.by_role_growth_6m_pct.Marketing  e.g. -50.0
headcount.by_role_growth_6m_pct.Human Resources  e.g. 0.0
headcount.by_role_growth_6m_pct.Education  e.g. 0.0
headcount.by_role_growth_6m_pct.Community and Social Services  e.g. 0.0
headcount.by_role_growth_6m_pct.Engineering  e.g. 0.0
headcount.by_role_growth_6m_pct.Information Technology  e.g. 0.0
headcount.by_role_growth_6m_pct.Quality Assurance  e.g. 0.0
headcount.by_role_growth_6m_pct.Arts and Design  e.g. -10.0
headcount.by_role_growth_6m_pct.Business Development  e.g. 0.0
headcount.by_role_growth_yoy_pct.Operations  e.g. 0.0
headcount.by_role_growth_yoy_pct.Program and Project Management  e.g. 0.0
headcount.by_role_growth_yoy_pct.Marketing  e.g. -50.0
headcount.by_role_growth_yoy_pct.Human Resources  e.g. 0.0
headcount.by_role_growth_yoy_pct.Education  e.g. 0.0
headcount.by_role_growth_yoy_pct.Community and Social Services  e.g. 0.0
headcount.by_role_growth_yoy_pct.Engineering  e.g. -2.7777777777777777
headcount.by_role_growth_yoy_pct.Information Technology  e.g. 0.0
headcount.by_role_growth_yoy_pct.Quality Assurance  e.g. 50.0
headcount.by_role_growth_yoy_pct.Arts and Design  e.g. -10.0
headcount.by_role_growth_yoy_pct.Business Development  e.g. 0.0
headcount.by_region_absolute.Madhya Pradesh, India  e.g. 1
headcount.by_region_absolute.Canada  e.g. 1
headcount.by_region_absolute.Greater Ahmedabad Area  e.g. 3
headcount.by_region_absolute.Jaipur  e.g. 1
headcount.by_region_absolute.Rajasthan, India  e.g. 1
headcount.by_region_absolute.Surat  e.g. 7
headcount.by_region_absolute.Ahmedabad  e.g. 2
headcount.by_region_absolute.India  e.g. 55
headcount.by_region_absolute.Indore  e.g. 1
headcount.by_region_absolute.Chorasi  e.g. 3
headcount.by_region_absolute.Ontario, Canada  e.g. 1
headcount.by_region_absolute.Gujarat, India  e.g. 52
headcount.by_region_absolute.Toronto, ON  e.g. 1
headcount.by_region_absolute.Greater Surat Area  e.g. 49
headcount.by_region_percent.Madhya Pradesh, India  e.g. 1.694915254237288
headcount.by_region_percent.Canada  e.g. 1.694915254237288
headcount.by_region_percent.Greater Ahmedabad Area  e.g. 5.084745762711865
headcount.by_region_percent.Jaipur  e.g. 1.694915254237288
headcount.by_region_percent.Rajasthan, India  e.g. 1.694915254237288
headcount.by_region_percent.Surat  e.g. 11.864406779661017
headcount.by_region_percent.Ahmedabad  e.g. 3.389830508474576
headcount.by_region_percent.India  e.g. 93.22033898305084
headcount.by_region_percent.Indore  e.g. 1.694915254237288
headcount.by_region_percent.Chorasi  e.g. 5.084745762711865
headcount.by_region_percent.Ontario, Canada  e.g. 1.694915254237288
headcount.by_region_percent.Gujarat, India  e.g. 88.13559322033898
headcount.by_region_percent.Toronto, ON  e.g. 1.694915254237288
headcount.by_region_percent.Greater Surat Area  e.g. 83.05084745762711
headcount.by_skill_absolute.Communication  e.g. 11
headcount.by_skill_absolute.PHP  e.g. 13
headcount.by_skill_absolute.MySQL  e.g. 15
headcount.by_skill_absolute.JavaScript  e.g. 18
headcount.by_skill_absolute.Java  e.g. 12
headcount.by_skill_absolute.Laravel  e.g. 8
headcount.by_skill_absolute.Cascading Style Sheets (CSS)  e.g. 16
headcount.by_skill_absolute.Figma (Software)  e.g. 8
headcount.by_skill_absolute.REST APIs  e.g. 8
headcount.by_skill_absolute.HTML  e.g. 14
headcount.by_skill_absolute.Swift (Programming Language)  e.g. 9
headcount.by_skill_absolute.jQuery  e.g. 10
headcount.by_skill_absolute.HTML5  e.g. 11
headcount.by_skill_absolute.Responsive Web Design  e.g. 9
headcount.by_skill_absolute.C++  e.g. 8
headcount.by_skill_absolute.Kotlin  e.g. 10
headcount.by_skill_absolute.Bootstrap (Framework)  e.g. 13
headcount.by_skill_absolute.SQL  e.g. 8
headcount.by_skill_absolute.Android Development  e.g. 8
headcount.by_skill_absolute.C (Programming Language)  e.g. 8
headcount.by_skill_absolute.Adobe Photoshop  e.g. 7
```

## company_enrich_4433230: fields of first record
```
crustdata_company_id  e.g. 4433230
funding.contact_email  e.g. null
funding.is_investor  e.g. false
funding.phone_number  e.g. null
funding.funds_total_usd  e.g. null
funding.last_fund_date  e.g. null
funding.num_funding_rounds  e.g. null
funding.num_funds  e.g. null
funding.total_investment_usd  e.g. null
funding.last_round_amount_usd  e.g. null
funding.last_round_type  e.g. null
funding.investors  e.g. null
funding.last_fundraise_date  e.g. null
headcount.largest_headcount_country  e.g. "IND"
headcount.total  e.g. 1
headcount.growth_percent.mom  e.g. -50.0
headcount.growth_percent.qoq  e.g. -50.0
headcount.growth_percent.six_months  e.g. -50.0
headcount.growth_percent.yoy  e.g. -50.0
headcount.growth_percent.two_years  e.g. -50.0
headcount.growth_absolute.mom  e.g. -1
headcount.growth_absolute.qoq  e.g. -1
headcount.growth_absolute.six_months  e.g. -1
headcount.growth_absolute.yoy  e.g. -1
headcount.growth_absolute.two_years  e.g. -1
headcount.by_role_absolute.Engineering  e.g. 2
headcount.by_role_absolute.Program and Project Management  e.g. 1
headcount.by_role_percent.Engineering  e.g. 200.0
headcount.by_role_percent.Program and Project Management  e.g. 100.0
headcount.by_role_growth_6m_pct.Engineering  e.g. 0.0
headcount.by_role_growth_yoy_pct.Engineering  e.g. 0.0
headcount.by_region_absolute.Surat  e.g. 1
headcount.by_region_absolute.Gujarat, India  e.g. 2
headcount.by_region_absolute.India  e.g. 2
headcount.by_region_absolute.Greater Surat Area  e.g. 1
headcount.by_region_percent.Surat  e.g. 100.0
headcount.by_region_percent.Gujarat, India  e.g. 200.0
headcount.by_region_percent.India  e.g. 200.0
headcount.by_region_percent.Greater Surat Area  e.g. 100.0
headcount.by_skill_absolute.Organization Skills  e.g. 1
headcount.by_skill_absolute.Android SDK  e.g. 1
headcount.by_skill_absolute.Facebook  e.g. 1
headcount.by_skill_absolute.Social Media Integration  e.g. 1
headcount.by_skill_absolute.Dropbox  e.g. 1
headcount.by_skill_absolute.JSON  e.g. 1
headcount.by_skill_absolute.Analytics  e.g. 1
headcount.by_skill_absolute.Google Calendar  e.g. 1
headcount.by_skill_absolute.Android  e.g. 1
headcount.by_skill_absolute.Mobile Application Development  e.g. 1
headcount.by_skill_absolute.Implementation Plans  e.g. 1
headcount.by_skill_absolute.Project Metrics  e.g. 1
headcount.by_skill_absolute.Resource Allocation  e.g. 1
headcount.by_skill_absolute.Analytical Skills  e.g. 1
headcount.by_skill_absolute.People Management  e.g. 1
headcount.by_skill_percent.Organization Skills  e.g. 100.0
headcount.by_skill_percent.Android SDK  e.g. 100.0
headcount.by_skill_percent.Facebook  e.g. 100.0
headcount.by_skill_percent.Social Media Integration  e.g. 100.0
headcount.by_skill_percent.Dropbox  e.g. 100.0
headcount.by_skill_percent.JSON  e.g. 100.0
headcount.by_skill_percent.Analytics  e.g. 100.0
headcount.by_skill_percent.Google Calendar  e.g. 100.0
headcount.by_skill_percent.Android  e.g. 100.0
headcount.by_skill_percent.Mobile Application Development  e.g. 100.0
headcount.by_skill_percent.Implementation Plans  e.g. 100.0
headcount.by_skill_percent.Project Metrics  e.g. 100.0
headcount.by_skill_percent.Resource Allocation  e.g. 100.0
headcount.by_skill_percent.Analytical Skills  e.g. 100.0
headcount.by_skill_percent.People Management  e.g. 100.0
headcount.timeseries[].date  e.g. "2023-01-30"
headcount.timeseries[].employee_count  e.g. 2
locations.city  e.g. "Utran, Utran Power House"
locations.country  e.g. "IND"
locations.state  e.g. "Gujarat"
locations.street_address  e.g. "Green Road VIP Circle, Utran, Utran Power House, Gujarat"
locations.headquarters  e.g. "Utran, Utran Power House, Gujarat, India"
locations.all_office_addresses[]  e.g. []
basic_info.status  e.g. "active"
basic_info.name  e.g. "Social Infotech"
basic_info.primary_domain  e.g. "socialinfotech.com"
basic_info.all_domains[]  e.g. ["socialinfotech.com"]
basic_info.website  e.g. "http://socialinfotech.com/"
basic_info.logo_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
basic_info.description  e.g. "Social Infotech IT Professional services exclusively focus 
basic_info.company_type  e.g. "Public Company"
basic_info.year_founded  e.g. 2014
basic_info.employee_count_range  e.g. "11-50"
basic_info.markets[]  e.g. ["PRIVATE"]
basic_info.crustdata_company_id  e.g. 4433230
basic_info.professional_network_id  e.g. "6614699"
basic_info.professional_network_url  e.g. "https://www.linkedin.com/company/socialinfotech"
basic_info.profile_name  e.g. "Social Infotech"
hiring.recent_titles_csv  e.g. null
hiring.openings_count  e.g. null
hiring.openings_growth_percent  e.g. null
hiring.by_function_qoq_pct  e.g. null
hiring.by_function_6m_pct  e.g. null
taxonomy.primary_naics_detail  e.g. null
taxonomy.sic_detail_list[]  e.g. []
taxonomy.categories[]  e.g. []
taxonomy.professional_network_industries[]  e.g. ["Software Development", "Technology, Information and Intern
taxonomy.professional_network_industry  e.g. "Software Development"
taxonomy.professional_network_specialities[]  e.g. ["Android Development", "Ios Development"]
_match.confidence_score  e.g. 1.0
_match.match_type  e.g. "crustdata_company_id"
_match.match_status  e.g. null
```

## company_enrich_631307: fields of first record
```
crustdata_company_id  e.g. 631307
funding.acquired_by[]  e.g. []
funding.acquisitions[].acquiree_company_id  e.g. 630577
funding.acquisitions[].acquiree_company_name  e.g. "DrawBridge Lending"
funding.acquisitions[].acquiree_crunchbase_url  e.g. "https://crunchbase.com/organization/drawbridge-lending"
funding.acquisitions[].acquirer_company_id  e.g. 631307
funding.acquisitions[].acquirer_company_name  e.g. "Galaxy Digital"
funding.acquisitions[].acquirer_crunchbase_url  e.g. "https://crunchbase.com/organization/galaxy-digital-lp"
funding.acquisitions[].announced_on_date  e.g. "2020-11-13"
funding.acquisitions[].transaction_text  e.g. "DrawBridge Lending acquired by Galaxy Digital"
funding.investors_detailed[].crunchbase_profile_url  e.g. "https://www.crunchbase.com/organization/ambush-capital"
funding.investors_detailed[].permalink  e.g. "ambush-capital"
funding.investors_detailed[].name  e.g. "Ambush Capital"
funding.investors_detailed[].uuid  e.g. "9b4513a5-8e32-45d0-8af9-bd5f1301e35a"
funding.investors_detailed[].type  e.g. "organization"
funding.investors_detailed[].categories[]  e.g. ["angel_group", "venture_capital"]
funding.milestones[].round_type  e.g. "post_ipo_debt"
funding.milestones[].is_fund  e.g. false
funding.milestones[].permalink  e.g. "galaxy-digital-lp-post-ipo-debt--ebc171c6"
funding.milestones[].date  e.g. "2026-07-27"
funding.milestones[].funding_date  e.g. "2026-07-27"
funding.milestones[].amount_usd  e.g. 30000000.0
funding.milestones[].investors  e.g. "K3 Capital"
funding.milestones[].lead_investors  e.g. null
funding.contact_email  e.g. "Paulgregory0000@gmail.com"
funding.is_investor  e.g. true
funding.phone_number  e.g. null
funding.funds[].amount_usd  e.g. 125250000.0
funding.funds[].date  e.g. "2026-08-11"
funding.funds[].investors_detailed[]  e.g. []
funding.funds[].name  e.g. "Galaxy Sharplink Onchain Yield Fund"
funding.funds[].num_investors  e.g. null
funding.funds[].permalink  e.g. "galaxy-digital-lp-raised-galaxy-sharplink-onchain-yield-fun
funding.funds_total_usd  e.g. 1333010592.0
funding.last_fund_date  e.g. "2026-08-11"
funding.num_funding_rounds  e.g. 14
funding.num_funds  e.g. 7
funding.total_investment_usd  e.g. 8745900000.0
funding.last_round_amount_usd  e.g. 30000000.0
funding.last_round_type  e.g. "post_ipo_debt"
funding.investors[]  e.g. ["Ambush Capital", "Arca"]
funding.last_fundraise_date  e.g. "2026-07-27"
headcount.largest_headcount_country  e.g. "USA"
headcount.total  e.g. 2692
headcount.growth_percent.mom  e.g. 0.07434944237918216
headcount.growth_percent.qoq  e.g. 1.355421686746988
headcount.growth_percent.six_months  e.g. 6.698374950455807
headcount.growth_percent.yoy  e.g. 19.22054915854739
headcount.growth_percent.two_years  e.g. 50.89686098654709
headcount.growth_absolute.mom  e.g. 2
headcount.growth_absolute.qoq  e.g. 36
headcount.growth_absolute.six_months  e.g. 169
headcount.growth_absolute.yoy  e.g. 434
headcount.growth_absolute.two_years  e.g. 908
headcount.by_role_absolute.Operations  e.g. 330
headcount.by_role_absolute.Support  e.g. 73
headcount.by_role_absolute.Education  e.g. 128
headcount.by_role_absolute.Business Development  e.g. 210
headcount.by_role_absolute.Engineering  e.g. 228
headcount.by_role_absolute.Sales  e.g. 227
headcount.by_role_absolute.Military and Protective Services  e.g. 42
headcount.by_role_absolute.Administrative  e.g. 179
headcount.by_role_absolute.Finance  e.g. 151
headcount.by_role_absolute.Human Resources  e.g. 62
headcount.by_role_absolute.Accounting  e.g. 55
headcount.by_role_absolute.Marketing  e.g. 62
headcount.by_role_absolute.Arts and Design  e.g. 87
headcount.by_role_absolute.Information Technology  e.g. 132
headcount.by_role_percent.Operations  e.g. 12.25854383358098
headcount.by_role_percent.Support  e.g. 2.711738484398217
headcount.by_role_percent.Education  e.g. 4.75482912332838
headcount.by_role_percent.Business Development  e.g. 7.800891530460624
headcount.by_role_percent.Engineering  e.g. 8.469539375928678
headcount.by_role_percent.Sales  e.g. 8.432392273402675
headcount.by_role_percent.Military and Protective Services  e.g. 1.5601783060921248
headcount.by_role_percent.Administrative  e.g. 6.649331352154532
headcount.by_role_percent.Finance  e.g. 5.609212481426449
headcount.by_role_percent.Human Resources  e.g. 2.3031203566121845
headcount.by_role_percent.Accounting  e.g. 2.0430906389301633
headcount.by_role_percent.Marketing  e.g. 2.3031203566121845
headcount.by_role_percent.Arts and Design  e.g. 3.231797919762259
headcount.by_role_percent.Information Technology  e.g. 4.903417533432393
headcount.by_role_growth_6m_pct.Support  e.g. 7.352941176470589
headcount.by_role_growth_6m_pct.Legal  e.g. 5.714285714285714
headcount.by_role_growth_6m_pct.Quality Assurance  e.g. -9.090909090909092
headcount.by_role_growth_6m_pct.Consulting  e.g. 0.0
headcount.by_role_growth_6m_pct.Entrepreneurship  e.g. -3.4482758620689653
headcount.by_role_growth_6m_pct.Human Resources  e.g. 14.814814814814813
headcount.by_role_growth_6m_pct.Arts and Design  e.g. 11.538461538461538
headcount.by_role_growth_6m_pct.Finance  e.g. 12.686567164179104
headcount.by_role_growth_6m_pct.Sales  e.g. 11.822660098522167
headcount.by_role_growth_6m_pct.Accounting  e.g. 3.7735849056603774
headcount.by_role_growth_6m_pct.Product Management  e.g. 0.0
headcount.by_role_growth_6m_pct.Healthcare Services  e.g. 11.11111111111111
headcount.by_role_growth_6m_pct.Program and Project Management  e.g. 4.166666666666666
headcount.by_role_growth_6m_pct.Purchasing  e.g. 80.0
headcount.by_role_growth_6m_pct.Operations  e.g. 11.486486486486488
headcount.by_role_growth_6m_pct.Community and Social Services  e.g. 0.0
headcount.by_role_growth_6m_pct.Real Estate  e.g. 6.666666666666667
headcount.by_role_growth_6m_pct.Information Technology  e.g. 11.864406779661017
headcount.by_role_growth_6m_pct.Research  e.g. 4.761904761904762
headcount.by_role_growth_6m_pct.Business Development  e.g. 7.6923076923076925
headcount.by_role_growth_6m_pct.Military and Protective Services  e.g. 10.526315789473683
headcount.by_role_growth_6m_pct.Engineering  e.g. 40.74074074074074
headcount.by_role_growth_6m_pct.Education  e.g. 12.280701754385964
headcount.by_role_growth_6m_pct.Customer Success and Support  e.g. 2.898550724637681
headcount.by_role_growth_6m_pct.Media and Communication  e.g. 5.714285714285714
headcount.by_role_growth_6m_pct.Marketing  e.g. 14.814814814814813
headcount.by_role_growth_6m_pct.Administrative  e.g. 9.815950920245399
headcount.by_role_growth_yoy_pct.Support  e.g. 2333.333333333333
headcount.by_role_growth_yoy_pct.Legal  e.g. 23.333333333333332
headcount.by_role_growth_yoy_pct.Quality Assurance  e.g. 11.11111111111111
headcount.by_role_growth_yoy_pct.Consulting  e.g. 0.0
headcount.by_role_growth_yoy_pct.Entrepreneurship  e.g. 3.7037037037037033
headcount.by_role_growth_yoy_pct.Human Resources  e.g. 34.78260869565217
headcount.by_role_growth_yoy_pct.Arts and Design  e.g. 33.84615384615385
headcount.by_role_growth_yoy_pct.Finance  e.g. 24.793388429752067
headcount.by_role_growth_yoy_pct.Sales  e.g. 26.111111111111114
headcount.by_role_growth_yoy_pct.Accounting  e.g. 17.02127659574468
headcount.by_role_growth_yoy_pct.Product Management  e.g. 81.81818181818183
```

## company_identify: fields of first record
```
crustdata_company_id  e.g. 897127
basic_info.name  e.g. "Razorpay"
basic_info.crustdata_company_id  e.g. 897127
basic_info.primary_domain  e.g. "razorpay.com"
basic_info.all_domains[]  e.g. ["curlec.com", "bitly.com"]
basic_info.website  e.g. "https://bit.ly/razorpay_learnmore"
basic_info.professional_network_url  e.g. "https://www.linkedin.com/company/razorpay"
basic_info.professional_network_id  e.g. "3788927"
basic_info.profile_name  e.g. "Razorpay"
basic_info.logo_permalink  e.g. "https://crustdata-media.s3.us-east-2.amazonaws.com/company/
basic_info.description  e.g. "Power your finance, grow your business.Razorpay is India\u2
basic_info.company_type  e.g. "Privately Held"
basic_info.year_founded  e.g. 2014
basic_info.employee_count_range  e.g. "1001-5000"
basic_info.markets[]  e.g. ["PRIVATE"]
basic_info.industries[]  e.g. ["Software Development", "Technology, Information and Intern
social_profiles  e.g. null
_match.confidence_score  e.g. 1.0
_match.match_type  e.g. "domain"
_match.match_status  e.g. null
```

## company_enrich: fields of first record
```
crustdata_company_id  e.g. 897127
funding.acquired_by[].amount_usd  e.g. null
funding.acquired_by[].crustdata_company_id  e.g. 897127
funding.acquired_by[].date  e.g. "2022-02-08"
funding.acquired_by[].name  e.g. "Razorpay"
funding.acquisitions[].acquiree_company_id  e.g. 10127
funding.acquisitions[].acquiree_company_name  e.g. "PoshVine"
funding.acquisitions[].acquiree_crunchbase_url  e.g. "https://crunchbase.com/organization/poshvine"
funding.acquisitions[].acquirer_company_id  e.g. 897127
funding.acquisitions[].acquirer_company_name  e.g. "Razorpay"
funding.acquisitions[].acquirer_crunchbase_url  e.g. "https://crunchbase.com/organization/razorpay"
funding.acquisitions[].announced_on_date  e.g. "2022-09-27"
funding.acquisitions[].transaction_text  e.g. "PoshVine acquired by Razorpay"
funding.investors_detailed[].crunchbase_profile_url  e.g. "https://www.crunchbase.com/person/abhay-singhal"
funding.investors_detailed[].permalink  e.g. "abhay-singhal"
funding.investors_detailed[].name  e.g. "Abhay Singhal"
funding.investors_detailed[].uuid  e.g. "b212c927-b833-a178-39e0-239a544635f6"
funding.investors_detailed[].type  e.g. "person"
funding.investors_detailed[].categories[]  e.g. ["angel"]
funding.milestones[].round_type  e.g. "secondary_market"
funding.milestones[].is_fund  e.g. false
funding.milestones[].permalink  e.g. "razorpay-secondary-market--bc7602c8"
funding.milestones[].date  e.g. "2022-05-10"
funding.milestones[].funding_date  e.g. "2022-05-10"
funding.milestones[].amount_usd  e.g. 75000000.0
funding.milestones[].investors  e.g. "Lightspeed Venture Partners, Axevil Capital, Moore Strategi
funding.milestones[].lead_investors  e.g. "Lightspeed Venture Partners"
funding.contact_email  e.g. "contact@razorpay.com"
funding.is_investor  e.g. false
funding.phone_number  e.g. "1800-123-1272"
funding.funds_total_usd  e.g. null
funding.last_fund_date  e.g. null
funding.num_funding_rounds  e.g. 10
funding.num_funds  e.g. 0
funding.total_investment_usd  e.g. 816600000.0
funding.last_round_amount_usd  e.g. 75000000.0
funding.last_round_type  e.g. "secondary_market"
funding.investors[]  e.g. ["Abhay Singhal", "Alkeon Capital"]
funding.last_fundraise_date  e.g. "2022-05-10"
headcount.largest_headcount_country  e.g. "IND"
headcount.total  e.g. 4027
headcount.growth_percent.mom  e.g. -0.3711034141514102
headcount.growth_percent.qoq  e.g. 0.39890301670406386
headcount.growth_percent.six_months  e.g. -0.8860447944868325
headcount.growth_percent.yoy  e.g. -3.1505531505531508
headcount.growth_percent.two_years  e.g. 9.429347826086957
headcount.growth_absolute.mom  e.g. -15
headcount.growth_absolute.qoq  e.g. 16
headcount.growth_absolute.six_months  e.g. -36
headcount.growth_absolute.yoy  e.g. -131
headcount.growth_absolute.two_years  e.g. 347
headcount.by_role_absolute.Sales  e.g. 367
headcount.by_role_absolute.Operations  e.g. 202
headcount.by_role_absolute.Research  e.g. 109
headcount.by_role_absolute.Finance  e.g. 266
headcount.by_role_absolute.Arts and Design  e.g. 83
headcount.by_role_absolute.Product Management  e.g. 129
headcount.by_role_absolute.Support  e.g. 128
headcount.by_role_absolute.Human Resources  e.g. 123
headcount.by_role_absolute.Engineering  e.g. 1041
headcount.by_role_absolute.Marketing  e.g. 102
headcount.by_role_absolute.Business Development  e.g. 504
headcount.by_role_absolute.Information Technology  e.g. 285
headcount.by_role_percent.Sales  e.g. 9.11348398311398
headcount.by_role_percent.Operations  e.g. 5.016141047926497
headcount.by_role_percent.Research  e.g. 2.7067295753662775
headcount.by_role_percent.Finance  e.g. 6.605413459150733
headcount.by_role_percent.Arts and Design  e.g. 2.0610876583064317
headcount.by_role_percent.Product Management  e.g. 3.2033772038738513
headcount.by_role_percent.Support  e.g. 3.178544822448473
headcount.by_role_percent.Human Resources  e.g. 3.0543829153215794
headcount.by_role_percent.Engineering  e.g. 25.85050906381922
headcount.by_role_percent.Marketing  e.g. 2.5329029053886267
headcount.by_role_percent.Business Development  e.g. 12.515520238390861
headcount.by_role_percent.Information Technology  e.g. 7.077228706232928
headcount.by_role_growth_6m_pct.Customer Success and Support  e.g. 3.389830508474576
headcount.by_role_growth_6m_pct.Business Development  e.g. 8.38709677419355
headcount.by_role_growth_6m_pct.Arts and Design  e.g. 6.41025641025641
headcount.by_role_growth_6m_pct.Support  e.g. 10.344827586206897
headcount.by_role_growth_6m_pct.Media and Communication  e.g. -31.57894736842105
headcount.by_role_growth_6m_pct.Administrative  e.g. 9.30232558139535
headcount.by_role_growth_6m_pct.Accounting  e.g. 0.0
headcount.by_role_growth_6m_pct.Legal  e.g. 21.428571428571427
headcount.by_role_growth_6m_pct.Information Technology  e.g. 0.7067137809187279
headcount.by_role_growth_6m_pct.Program and Project Management  e.g. -8.333333333333332
headcount.by_role_growth_6m_pct.Military and Protective Services  e.g. -14.285714285714285
headcount.by_role_growth_6m_pct.Sales  e.g. 5.459770114942529
headcount.by_role_growth_6m_pct.Research  e.g. -10.655737704918032
headcount.by_role_growth_6m_pct.Engineering  e.g. -5.877034358047016
headcount.by_role_growth_6m_pct.Quality Assurance  e.g. 31.57894736842105
headcount.by_role_growth_6m_pct.Operations  e.g. 0.4975124378109453
headcount.by_role_growth_6m_pct.Product Management  e.g. 0.0
headcount.by_role_growth_6m_pct.Real Estate  e.g. 100.0
headcount.by_role_growth_6m_pct.Human Resources  e.g. 8.849557522123893
headcount.by_role_growth_6m_pct.Finance  e.g. 7.258064516129033
headcount.by_role_growth_6m_pct.Purchasing  e.g. -16.666666666666664
headcount.by_role_growth_6m_pct.Marketing  e.g. 0.9900990099009901
headcount.by_role_growth_6m_pct.Healthcare Services  e.g. 20.0
headcount.by_role_growth_6m_pct.Entrepreneurship  e.g. 45.0
headcount.by_role_growth_6m_pct.Education  e.g. 0.0
headcount.by_role_growth_6m_pct.Community and Social Services  e.g. -18.181818181818183
headcount.by_role_growth_6m_pct.Consulting  e.g. -4.444444444444445
headcount.by_role_growth_yoy_pct.Customer Success and Support  e.g. 7.964601769911504
headcount.by_role_growth_yoy_pct.Business Development  e.g. 14.80637813211845
headcount.by_role_growth_yoy_pct.Arts and Design  e.g. -2.3529411764705883
headcount.by_role_growth_yoy_pct.Support  e.g. 13.274336283185843
headcount.by_role_growth_yoy_pct.Media and Communication  e.g. -43.47826086956522
headcount.by_role_growth_yoy_pct.Administrative  e.g. 20.51282051282051
headcount.by_role_growth_yoy_pct.Accounting  e.g. 8.0
headcount.by_role_growth_yoy_pct.Legal  e.g. 13.333333333333334
headcount.by_role_growth_yoy_pct.Information Technology  e.g. 7.954545454545454
headcount.by_role_growth_yoy_pct.Program and Project Management  e.g. -12.698412698412698
headcount.by_role_growth_yoy_pct.Military and Protective Services  e.g. 9.090909090909092
headcount.by_role_growth_yoy_pct.Sales  e.g. -5.412371134020619
headcount.by_role_growth_yoy_pct.Research  e.g. -9.166666666666666
headcount.by_role_growth_yoy_pct.Engineering  e.g. -11.101622544833475
headcount.by_role_growth_yoy_pct.Quality Assurance  e.g. 4.166666666666666
headcount.by_role_growth_yoy_pct.Operations  e.g. 16.76300578034682
headcount.by_role_growth_yoy_pct.Product Management  e.g. 4.878048780487805
headcount.by_role_growth_yoy_pct.Real Estate  e.g. 100.0
```

## company_search: fields of first record
```
crustdata_company_id  e.g. 6
metadata.growth_calculation_date  e.g. "2026-10-27T23:08:48+00:00"
metadata.updated_at  e.g. "2026-10-30T00:23:30Z"
metadata.indexed_at  e.g. "2026-10-30T00:23:30Z"
basic_info.name  e.g. "a2z Infrastructure (P) Ltd"
basic_info.crustdata_company_id  e.g. 6
basic_info.primary_domain  e.g. "a2zgroup.co.in"
basic_info.all_domains[]  e.g. ["a2zgroup.co.in"]
basic_info.website  e.g. "http://www.a2zgroup.co.in"
basic_info.professional_network_url  e.g. "https://www.linkedin.com/company/a2z-infrastructure-p-ltd"
basic_info.professional_network_id  e.g. "429392"
basic_info.profile_name  e.g. "a2z Infrastructure (P) Ltd"
basic_info.logo_permalink  e.g. ""
basic_info.description  e.g. "Our Company is fastest growing EPC Business Enterprise in T
basic_info.company_type  e.g. "Privately Held"
basic_info.status  e.g. "active"
basic_info.year_founded  e.g. 2002
basic_info.employee_count_range  e.g. "201-500"
basic_info.markets[]  e.g. ["NSE", "BSE"]
revenue.estimated.lower_bound_usd  e.g. 20000000
revenue.estimated.upper_bound_usd  e.g. 50000000
revenue.public_markets.ipo_date  e.g. null
revenue.public_markets.stock_symbols[]  e.g. ["533292", "A2ZGROUP"]
revenue.public_markets.fiscal_year_end  e.g. ""
revenue.acquisition_status  e.g. ""
headcount.total  e.g. 321
software_reviews  e.g. null
funding.is_investor  e.g. false
funding.contact_email  e.g. "info@a2zemail.com"
funding.phone_number  e.g. "+91 124 4723383"
funding.total_investment_usd  e.g. 0.0
funding.last_round_amount_usd  e.g. null
funding.last_fundraise_date  e.g. null
funding.last_round_type  e.g. ""
funding.investors  e.g. null
hiring  e.g. null
locations.country  e.g. "IND"
locations.headquarters  e.g. "India"
locations.street_address  e.g. "India"
locations.city  e.g. null
locations.state  e.g. null
locations.all_office_addresses[]  e.g. []
maps  e.g. null
social_profiles.twitter_url  e.g. "https://x.com/A2ZMES"
social_profiles.professional_network.url  e.g. "https://www.linkedin.com/company/a2z-infrastructure-p-ltd"
social_profiles.professional_network.id  e.g. "429392"
taxonomy.professional_network_industry  e.g. "Oil and Gas"
followers.count  e.g. 948
followers.mom_percent  e.g. 0.10559662090813093
followers.qoq_percent  e.g. 0.6369426751592357
followers.six_months_growth_percent  e.g. 1.282051282051282
followers.yoy_percent  e.g. 1.8259935553168638
```

## job_search: fields of first record
```
company.basic_info.crustdata_company_id  e.g. 1906482
company.basic_info.industries[]  e.g. ["Information Technology & Services"]
company.basic_info.name  e.g. "DaCodes."
company.basic_info.primary_domain  e.g. "dacodes.com"
company.basic_info.professional_network_id  e.g. "10017588"
company.basic_info.website  e.g. "https://dacodes.com"
company.competitors.websites[]  e.g. []
company.followers.count  e.g. 74290
company.funding.investors  e.g. null
company.funding.last_fundraise_date  e.g. null
company.funding.last_round_type  e.g. ""
company.funding.num_funding_rounds  e.g. null
company.funding.total_investment_usd  e.g. null
company.funding.valuation_usd  e.g. 0.0
company.headcount.largest_headcount_country  e.g. "MEX"
company.headcount.range  e.g. "201-500"
company.headcount.total  e.g. 231
company.locations.city  e.g. null
company.locations.country  e.g. "United States"
company.locations.state  e.g. "Texas"
company.locations.street_address  e.g. "2700 Post Oak Blvd Galleria Office Tower I,, Houston, Texas
company.revenue.acquisition_status  e.g. null
company.revenue.estimated.lower_bound_usd  e.g. 20000000
company.revenue.estimated.upper_bound_usd  e.g. 50000000
company.revenue.public_markets.fiscal_year_end  e.g. ""
company.revenue.public_markets.stock_symbols[]  e.g. ["DACODES."]
content.description  e.g. "\u00a1Trabaja en DaCodes!\n\nSomos una firma de expertos en
crustdata_job_id  e.g. 7568043464686551
job_details.category  e.g. "Engineering"
job_details.employment_type  e.g. "full_time"
job_details.job_id  e.g. 7568043464686551
job_details.number_of_openings  e.g. null
job_details.reposted_job  e.g. false
job_details.source  e.g. "professional_network"
job_details.title  e.g. "Backend Engineer (Nodejs/TypeScript)"
job_details.url  e.g. "https://www.linkedin.com/jobs/view/4483764607"
job_details.workplace_type  e.g. null
location.city  e.g. "Mexico City"
location.country  e.g. "Mexico"
location.district  e.g. null
location.pincode  e.g. null
location.raw  e.g. "Mexico City, Mexico"
location.state  e.g. "Mexico City"
metadata.date_added  e.g. "2026-10-26T23:37:26"
metadata.date_updated  e.g. "2026-10-27T00:00:00"
```

## web_search: fields of first record
```
source  e.g. "web"
title  e.g. "Razorpay Salaries 2026 in India, Average salary \u20b926 la
url  e.g. "https://www.google.com/goto?url=CAESXwHrOzAV3dhqnYzm_2E9asg
snippet  e.g. "70% salaries range between \u20b9 13 lakhs to \u20b9 120 la
position  e.g. 1
```

## web_fetch: fields of first record
```
success  e.g. true
url  e.g. "https://razorpay.com/about/"
timestamp  e.g. 1793422876
title  e.g. "About Razorpay and The Team Behind it"
content  e.g. "<html lang=\"en-IN\" style=\"overscroll-behavior-y:none\" c
http_status  e.g. 200
```
