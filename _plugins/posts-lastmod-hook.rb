#!/usr/bin/env ruby
#
# Check for changed posts
require 'open3'

Jekyll::Hooks.register :posts, :post_init do |post|

  commit_num, _ = Open3.capture2('git', 'rev-list', '--count', 'HEAD', post.path)

  if commit_num.to_i > 1
    lastmod_date, _ = Open3.capture2('git', 'log', '-1', '--pretty=%ad', '--date=iso', post.path)
    post.data['last_modified_at'] = lastmod_date.strip
  end

end
