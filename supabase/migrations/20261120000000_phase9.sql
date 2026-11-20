-- Phase 9: ক্যাটাগরি সম্প্রসারণ (১৫টা ক্যাটাগরি)
-- নতুন ৮টা ক্যাটাগরির সারি। config/categories.json-এ এগুলো প্রথমে বন্ধ (enabled: false) থাকে।
-- আগে চালানো থাকলে আবার চালানো নিরাপদ (on conflict do nothing)। কোনো টেবিল বা ফাংশন বদলায় না।
-- জরুরি: এই সারি না থাকলে স্ক্র্যাপার ওই ক্যাটাগরির listing-এ category_id বসাতে পারে না (ফাঁকা থাকে) এবং ড্যাশবোর্ডের ক্যাটাগরি-ফিল্টারে দেখা যায় না।
insert into categories (slug, name) values
  ('mobile-accessories', 'মোবাইল অ্যাক্সেসরিজ'),
  ('bags-footwear',      'ব্যাগ ও জুতা'),
  ('islamic',            'ইসলামিক পণ্য'),
  ('health-wellness',    'হেলথ ও ওয়েলনেস'),
  ('watches-jewellery',  'ঘড়ি ও গয়না'),
  ('gifts-lifestyle',    'গিফট ও লাইফস্টাইল'),
  ('grocery',            'গ্রোসারি'),
  ('automotive',         'অটোমোটিভ')
on conflict (slug) do nothing;
